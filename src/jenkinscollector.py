# Copyright (C) Schweizerische Bundesbahnen SBB, 2016
# Python 3.4
from collector import ClientCert

__author__ = 'florianseidl'

from urllib.request import HTTPError, URLError
from datetime import datetime
from concurrent import futures
import json
import logging
import sys
from collector import create_http_client, configure_client_cert
from configutil import decrypt
from cimon import JobStatus,RequestStatus,Health
from urllib.parse import urlparse

# Collect the build status in jenins via rest requests.
# will request the status of the latestBuild of each job configured and each job in each view configured
# views will be updated periodically
#
# is collector type "build" (only one collector of each type is allowed)
#
# the result returned is transformed form the actual jenkins api (in order to encapsulate the jenkins specific things)
#
# returns a dict per job (job_name) and containing JobStatus objects
# the "request_status" allways has to be checked first, only if it is OK the further values are contained
# { (<hostname>, <job_name_as_string>) : JobStatus }
#
default_max_parallel_requests=7
default_update_views_every = 50
default_view_depth=0

logger = logging.getLogger(__name__)

def create(configuration, key=None):
    return JenkinsCollector(base_url = configuration["url"],
                            username = configuration.get("user", None),
                            password = configuration.get("password", None) or decrypt(configuration.get("passwordEncrypted", None), key),
                            jwt_login_url = configuration.get("jwtLoginUrl", None),
                            saml_login_url = configuration.get("samlLoginUrl", None),
                            job_names= configuration.get("jobs", ()),
                            view_names = configuration.get("views", ()),
                            max_parallel_requests = configuration.get("maxParallelRequest", default_max_parallel_requests),
                            verify_ssl = configuration.get("verifySsl", True),
                            view_depth = configuration.get("viewDepth", default_view_depth),
                            client_cert = configure_client_cert(configuration.get("clientCert", None), key),
                            name = configuration.get('name', None))

class JenkinsCollector:
    # extract result and building state from the colors in the view
    colors_to_result = {"red" : Health.SICK,
                        "yellow" : Health.UNWELL,
                        "blue" : Health.HEALTHY,
                        "notbuilt" : Health.UNDEFINED}
    jenkins_result_to_result = {"SUCCESS" : Health.HEALTHY,
                                "UNSTABLE" : Health.UNWELL,
                                "FAILURE": Health.SICK}

    def __init__(self,
                 base_url,
                 username = None,
                 password = None,
                 job_names =(),
                 view_names = (),
                 max_parallel_requests=default_max_parallel_requests,
                 jwt_login_url=None,
                 saml_login_url=None,
                 verify_ssl=True,
                 view_depth=default_view_depth,
                 client_cert=None,
                 name=None):
        self.jenkins = JenkinsClient(http_client=create_http_client(base_url=base_url,
                                                                    username=username,
                                                                    password=password,
                                                                    jwt_login_url=jwt_login_url,
                                                                    saml_login_url=saml_login_url,
                                                                    verify_ssl=verify_ssl,
                                                                    client_cert=client_cert),
                                                                    view_depth=view_depth)
        self.job_names = tuple(job_names)
        self.view_names = tuple(view_names)
        self.max_parallel_requests = max_parallel_requests
        self.last_results={}
        self.name = name if name else urlparse(base_url).netloc

    def collect(self):
        method_param = [(self.collect_job, job_name) for job_name in self.job_names] + \
                       [(self.collect_view, view_name) for view_name in self.view_names]

        with futures.ThreadPoolExecutor(max_workers=self.max_parallel_requests) as executor:
            future_requests = {executor.submit(method, param):
                                    (method, param) for method, param in method_param}

        builds = {}
        for future_request in futures.as_completed(future_requests):
            builds.update(future_request.result())

        logger.debug("Build status collected: %s", builds)
        return builds

    def qualified_job_name(self, job_name):
        return self.name, job_name

    def collect_job(self, job_name):
        job_name, req_status, jenkins_build = self.__latest_build__(job_name)
        if req_status == RequestStatus.OK:
            return { self.qualified_job_name(job_name) : self.__convert_build__(job_name, jenkins_build)}
        else:
            return {self.qualified_job_name(job_name): JobStatus(request_status=req_status)}

    def __latest_build__(self, job_name):
        try:
            return (job_name, RequestStatus.OK, self.jenkins.latest_build(job_name))
        except HTTPError as e:
            # ignore...
            if(e.code == 404): # not found - its OK lets not crash
                logger.warning("No build found for job %s" % job_name)
                return (job_name, RequestStatus.NOT_FOUND, None)
            else:
                logger.exception("HTTP Error requesting status for job %s" % job_name)
                return (job_name, RequestStatus.ERROR, None)
        except URLError as e:
            logger.exception("URL Error requesting status for job %s" % job_name)
            return (job_name, RequestStatus.ERROR, None)

    def __convert_build__(self, job_name, jenkins_build_result):
        status = JobStatus(
            health=self.__convert_store_fill_job_result__(job_name, jenkins_build_result["result"]),
            active=jenkins_build_result["building"],
            timestamp=datetime.fromtimestamp(jenkins_build_result["timestamp"]/1000.0),
            number=jenkins_build_result["number"],
            names=[culprit["fullName"] for culprit in jenkins_build_result["culprits"]] if "culprits" in jenkins_build_result else [])
        logger.debug("Converted Build result: %s", str(status))
        return status

    def __convert_store_fill_job_result__(self, job_name, jenkins_result):
        if jenkins_result:
            result = self.jenkins_result_to_result[jenkins_result] if jenkins_result in self.jenkins_result_to_result else Health.OTHER
            self.last_results[job_name] = result
            return result
        else:
            return self.last_results[job_name] if job_name in self.last_results else Health.OTHER

    def collect_view(self, view_name):
        # separate method because default parameter does not work easily with future
        return self.__collect_view_recursive__(view_name, set())

    def __collect_view_recursive__(self, view_name, allready_visited):
        if view_name in allready_visited: # guard against infinite loops
            return {}
        allready_visited.add(view_name)

        view = self.__view__(view_name)
        if view:
            # add the builds to the existing ones (from recursion)
            builds = self.__extract_job__status__(view)
            if "views" in view:
                nested_views = self.__extract_nested_view_names__(view)
                for nested_view in nested_views:
                    # recurse for all nested views
                    builds.update(self.__collect_view_recursive__(nested_view, allready_visited))
            return builds
        else:
            return {self.qualified_job_name(view_name) : JobStatus(request_status=RequestStatus.ERROR)}

    def __extract_job__status__(self, view):
        builds = {}
        for job in view["jobs"]:
            jobname = job["name"]
            status = None
            if "color" in job:
                color_status_building = job["color"].split("_") if job["color"] else (None,)
                if color_status_building[0] == "disabled":
                    status = JobStatus(request_status=RequestStatus.NOT_FOUND)
                elif color_status_building[0] in self.colors_to_result:
                    status = JobStatus(
                        health= self.colors_to_result[color_status_building[0]],
                        active = len(color_status_building) > 1 and color_status_building[1] == "anime")
                else:
                     status = JobStatus(health=Health.OTHER)
            if status and "builds" in job: # requires depth 2
                latest_build = self.__latest_build_in_view__(job)
                if "number" in latest_build:
                    status.number = latest_build["number"]
                if "timestamp" in latest_build:
                    status.timestamp = datetime.fromtimestamp(latest_build["timestamp"] / 1000)
                if "culprits" in latest_build:
                    status.names = [culprit["fullName"] for culprit in latest_build["culprits"]]
            if status:
                builds[jobname] = status
        return builds

    def __latest_build_in_view__(self, job):
        latest = {}
        for build in job["builds"]: # sort by number
            if not latest or "number" in build and latest["number"] < build["number"]:
                latest = build
        return latest

    def __extract_nested_view_names__(self, view):
        views = []
        for v in view["views"]:
            #"url":"https://ci.sbb.ch/view/mvp/view/zvs-drittgeschaeft/view/vermittler-westernunion/
            url = v["url"] # extract name with path from url
            name_with_path = url.partition("view")[2]
            if name_with_path.endswith("/"):
                name_with_path = name_with_path[:-1]
            if name_with_path:
                views.append(name_with_path)
        return set(views)

    def __view__(self, view_name):
        try:
            return self.jenkins.view(view_name)
        except:
            # ignore...
            logger.exception("Error occured requesting info for view %s" % view_name)

class JenkinsClient():
    """ copied and simplifed from jenkinsapi by Willow Garage in order to ensure singe requests for latest build
        as oposed to multiple requests and local status"""
    def __init__(self, http_client,view_depth=default_view_depth):
        self.http_client = http_client
        self.view_depth=view_depth

    def latest_build(self, job_name):
        return json.loads(self.http_client.open_and_read("/job/%s/lastBuild/api/json?depth=0" % job_name))

    def view(self, view_name):
        return json.loads(self.http_client.open_and_read("/view/%s/api/json?depth=%d" % (view_name,self.view_depth)))

if  __name__ =='__main__':
    base_url = sys.argv[1]
    build = sys.argv[2]

    if not base_url or not build:
        print("Usage: python3 jenkinscollectory.py <base_url> <build>")
        exit(42)

    """smoke test"""
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    collector = JenkinsCollector(base_url,
                                 job_names = [build],
                                 view_names = [])
    print(collector.collect())
