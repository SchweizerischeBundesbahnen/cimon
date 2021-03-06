# Copyright (C) Schweizerische Bundesbahnen SBB, 2016
# Python 3.4
__author__ = 'florianseidl'

from output import AbstractBuildAmpel, default_signal_error_threshold
import os
from threading import Thread, Condition
from datetime import datetime, timedelta
import logging
import platform
from time import sleep

default_flash_interval_sec=1.5
default_absoulte_every_sec=300

logger = logging.getLogger(__name__)

# controll the cleware usb ampel (http://www.cleware-shop.de/epages/63698188.sf/de_DE/?ObjectPath=/Shops/63698188/Products/43/SubProducts/43-1)
# uses the shell cleware tool (as user) as no python binding worked. Unfortunately this is kind of slow.
# Extends AbstractBuildAmpel. See AbstractBuildAmpel for explaination of the logic (when does which light turn on)
def create(configuration, aesKey=None):
    return ClewareBuildAmpel(device=configuration.get("device", None),
                             signal_error_threshold=configuration.get("signalErrorThreshold", default_signal_error_threshold),
                             flash_interval_sec=configuration.get("flashIntervalSec", default_flash_interval_sec),
                             absoulte_every_sec=configuration.get("absoulteEverySec", default_absoulte_every_sec),
                             build_filter_pattern=configuration.get("buildFilterPattern", None),
                             collector_filter_pattern=configuration.get("collectorFilterPattern", None))


class ClewareBuildAmpel(AbstractBuildAmpel):
    """control the cleware ampel according to build status"""

    def __init__(self, device=None,
                 signal_error_threshold=default_signal_error_threshold,
                 flash_interval_sec=default_flash_interval_sec,
                 absoulte_every_sec=default_absoulte_every_sec,
                 build_filter_pattern=None,
                 collector_filter_pattern=None):
        super().__init__(signal_error_threshold=signal_error_threshold, build_filter_pattern=build_filter_pattern,collector_filter_pattern=collector_filter_pattern)
        self.cleware_ampel=ClewarecontrolClewareAmpel(device=device, flash_interval_sec=flash_interval_sec, absoulte_every_sec=absoulte_every_sec)

    def signal(self, red, yellow, green, flash=False):
        self.cleware_ampel.display(red=red, yellow=yellow, green=green, flash=flash)

    def close(self):
        super().close()
        self.cleware_ampel.wait_for_display()
        self.cleware_ampel.stop()

class ClewarecontrolClewareAmpel():
    """control the cleware ampel using the clewarecontrol shell command """
    red_light=0
    yellow_light=1
    green_light=2

    def __init__(self, device=None, flash_interval_sec=default_flash_interval_sec, absoulte_every_sec=default_absoulte_every_sec):
        self.device=device
        self.flash_interval_sec = flash_interval_sec
        self.to_display = (False, False, False)
        self.__stopped = True
        self.condition = Condition() # condition has its own (r)lock
        self.udpated = False
        self.current_display = (None, None, None)
        self.absolute_every = timedelta(seconds=absoulte_every_sec)
        self.__absolute_next = datetime.now() + self.absolute_every

    def wait_for_display(self, timeout=7):
        end = datetime.now() + timedelta(seconds=timeout)
        with self.condition:
            while datetime.now() < end and self.current_display != self.to_display:
                self.condition.wait(timeout=max((end - datetime.now()).total_seconds(), 0.01)) # wait for at least 10 milliseonds to release lock

    def stop(self):
        with self.condition:
            self.__stopped = True
            self.condition.notify_all()
            logger.debug("Output Thread stop")

    def display(self, red=False, yellow=False, green=False, flash=False):
        with self.condition:
            logger.debug("New values...." + str(locals()))
            self.to_display =  (red, yellow, green)
            self.flash = flash
            self.updated = True
            # start the output thread if required...
            if self.__stopped:
                self.__stopped = False
                Thread(target=self.output_loop).start()
            self.condition.notify_all()

    def output_loop(self):
        flash_state = False
        logger.debug("Starting Clewareampel Output Thread....")
        while not self.__stopped:
            with self.condition:
                logger.debug("flashinterval %s %s" % (str(self.flash_interval_sec), str(self.flash)))
                if self.flash_interval_sec >= 0 and self.flash:
                    logger.debug("Output with flash...")
                    wait_until, flash_state = self.__do_output_flash__(flash_state)
                else:
                    logger.debug("Output without flash...")
                    wait_until, flash_state = self.__do_output_no_flash__()
                while not self.__stopped and not self.updated and (not wait_until or wait_until > datetime.now()):
                    # if no flashing, wait forever, else wait for the next flash signal
                    # in any case wait at least 10 millis to release the lock and allow for signalling
                    timeout = (wait_until - datetime.now()).total_seconds() if wait_until else None
                    logger.debug("Waiting with timeout %s", str(timeout))
                    self.condition.wait(timeout=timeout)
        logger.info("Clewareampel Output Thread stopped.")


    def __do_output_no_flash__(self):
        logger.debug("Switch on: %s", self.to_display)
        self.__output_to_cleware__(*self.to_display)
        self.updated = False
        return None, False

    def __do_output_flash__(self, flash_state):
        if flash_state:
            logger.debug("Flash off")
            self.__output_to_cleware__(red=False, yellow=False, green=False)
        else:
            logger.debug("Flash on: %s", self.to_display)
            self.__output_to_cleware__(*self.to_display)
        self.updated = False
        # if currently off (flash state True as it is the previous state) then show for 1/5, else if on for 4/5 of the time
        interval = self.flash_interval_sec * 0.2 if flash_state else self.flash_interval_sec * 0.8
        return datetime.now() + timedelta(seconds=interval), not flash_state

    def __output_to_cleware__(self, red, yellow, green):
        if datetime.now() >= self.__absolute_next:
            logger.debug("Absolute output to cleware ampel")
            if self.__call_clewarecontrol__((self.red_light, red), (self.yellow_light, yellow), (self.green_light, green)):
                self.current_display = (red, yellow, green)
                self.__absolute_next = datetime.now() + self.absolute_every
        elif self.current_display != (red, yellow, green):
            switches = [(light, on) for (light, on, current) in ((self.red_light, red, self.current_display[0]),
                                                                 (self.yellow_light, yellow, self.current_display[1]),
                                                                 (self.green_light, green, self.current_display[2])) if on != current]
            logger.debug("Relative output to cleware ampel")
            if self.__call_clewarecontrol__(*switches):
                self.current_display = (red, yellow, green)
        else:
            logger.debug("No change and not time for absolute output, doing nothing.")

    def __call_clewarecontrol__(self, *light_on):
        # enable null device on Windows for test purposees
        nulldevice = "NUL" if platform.system() == "Windows" else "/dev/null"
        device_str = "-d %s " % self.device if self.device else ""
        command = ""
        for light, on in light_on:
            if command:
                command += " && "
            command += "clewarecontrol %s-c 1 -as %s %s > %s 2>&1" % (device_str, light, int(on), nulldevice)
        logger.debug(command)
        rc = os.system(command)
        if rc != 0:
            logger.warning("clewarecontrol returned %s", rc)
            return False
        return True

if  __name__ =='__main__':
    """smoke test"""
    a = ClewareBuildAmpel()
    a.self_check()
