__author__ = 'florianseidl'

import env
from cimon import *
import cimon
from unittest import TestCase
from unittest.mock import MagicMock, Mock
from types import SimpleNamespace
from datetime import datetime
import yaml

class CimonTest(TestCase):

    def test_run_0_collector_0_output(self):
        c = Cimon()
        c.collectors = tuple()
        c.outputs = tuple()
        c.run()

    def test_run_1_collector_1_output_empty_status(self):
        self.__do_run__(1, mock={})

    def test_run_1_collector_1_output_1_status(self):
        self.__do_run__(1, mock={ "b" : JobStatus(), "e": JobStatus()})

    def test_run_1_collector_1_output_3_status(self):
        self.__do_run__(1, mock={ "b" : JobStatus(), "e": JobStatus(),
                                  "y" : JobStatus(),
                                  "e" : JobStatus()})

    def test_run_1_collector_3_output_1_status(self):
        self.__do_run__(3, mock={ "b" : JobStatus(), "e": JobStatus()})

    def test_run_3_collector_1_output_1_status(self):
        self.__do_run__(1, mock={"a" : JobStatus(), "e": JobStatus()},
                        other_mock={"bla" : JobStatus()},
                        another_mock={"nice" : JobStatus() })

    def test_run_2_collector_same_type_1_output_1_status(self):
        c = Cimon(collectors = ( self.__mock_collector__("mock",{("mock","a") : JobStatus(), ("mock","e") : JobStatus()}),
                                 self.__mock_collector__("mock",{("mock","x") : JobStatus()})),
                  outputs = tuple((self.__mock_output__(),)))
        c.run()
        c.outputs[0].on_update.assert_called_once_with({("mock","a") :JobStatus(), ("mock","e"): JobStatus(), ("mock","x") : JobStatus()})

    def test_run_1_collector_1_output_status_none(self):
        self.__do_run__(1, mock={})

    def test_run_0_collector_1_output(self):
        self.__do_run__(1)

    def test_run_1_collector_0_output(self):
        self.__do_run__(1, mock={"b" : JobStatus(), "e": JobStatus()})

    def test_stop_calls_close(self):
        c = Cimon(outputs = (self.__mock_output__(close_method=True), self.__mock_output__(), self.__mock_output__(close_method=True)))
        c.rescheduler = SimpleNamespace()
        c.rescheduler.stop = MagicMock(spec=(""))
        c.stop()
        c.outputs[0].close.assert_called_once_with()
        c.outputs[2].close.assert_called_once_with()


    def __do_run__(self, nr_outputs=1, **collector_status):
        c = Cimon(collectors = tuple(self.__mock_collector__(name, self.__qualify_status__(name, status)) for name, status in collector_status.items()),
                  outputs = tuple(self.__mock_output__() for x in range(nr_outputs)))
        c.run()
        expected_status = {}
        for col in collector_status:
            expected_status.update(self.__qualify_status__(col, collector_status[col]))
        for output in c.outputs:
            output.on_update.assert_called_once_with(expected_status)

    def __qualify_status__(self, col, unqualified_status):
        return {(col,k):v for k,v in unqualified_status.items()}


    def __mock_collector__(self, type, status):
        collector = SimpleNamespace()
        collector.type = type
        collector.collect = MagicMock(spec=(""), return_value = status)
        return collector

    def __mock_output__(self, open_method=False, close_method=False):
        output = SimpleNamespace()
        output.on_update = MagicMock(spec=(""))
        if open_method:
            output.open = MagicMock(spec=(""))
        if close_method:
            output.close = MagicMock(spec=(""))
        return output

class CimonOperatingDaysHoursTest(TestCase):

    def test_parse_hours_or_days_1(self):
        self.assertEqual(cimon.__parse_hours_or_days__(1, None), (1, ))
        self.assertEqual(cimon.__parse_hours_or_days__("1", None), (1, ))

    def test_parse_hours_or_days_None(self):
        self.assertIsNone(cimon.__parse_hours_or_days__(None, None))

    def test_parse_hours_or_days_4_to_15(self):
        self.assertEqual(cimon.__parse_hours_or_days__("4-15", None), tuple(range(4, 16)))

    def test_parse_hours_or_days_4_5_6(self):
        self.assertEqual(cimon.__parse_hours_or_days__("4,5,6", None), (4,5,6))

    def test_parse_hours_or_days_None(self):
        self.assertEqual(cimon.__parse_hours_or_days__(None, "0-6"), (0,1,2,3,4,5,6))

    def test_parse_hours_or_days_None(self):
        self.assertEqual(cimon.__parse_hours_or_days__("*", "0-6"), (0,1,2,3,4,5,6))

    def test_parse_hours_or_days_4_5_6_9_to_12(self):
        self.assertEqual(cimon.__parse_hours_or_days__("4,5,6,9-12", None), (4,5,6,9,10,11,12))

    def test_parse_hours_or_days_4_to_6_9_to_12(self):
        self.assertEqual(cimon.__parse_hours_or_days__("4-6,9-12", None), (4,5,6,9,10,11,12))

    def test_parse_hours_or_days_4_to_6_5_to_9(self):
        self.assertEqual(cimon.__parse_hours_or_days__("4-6,5-9", None), (4,5,6,7,8,9))

    def test_parse_hours_or_days_4_to_6_5(self):
        self.assertEqual(cimon.__parse_hours_or_days__("4-6,5", None), (4,5,6))

    def test_parse_hours_or_days_21_to_3(self):
        self.assertRaises(ValueError, cimon.__parse_hours_or_days__,"21-3", None)

    def test_parse_hours_or_days_21_to_nothing(self):
        # fails because of split
        self.assertRaises(ValueError, cimon.__parse_hours_or_days__,"21-", None)

    def test_parse_hours_or_days_21_to_nothing(self):
        # fails because no number
        self.assertRaises(ValueError, cimon.__parse_hours_or_days__,"hotzenplotz,6", None)

    def test_parse_hours_or_days_star(self):
        # * should refer to the default
        self.assertEqual(cimon.__parse_hours_or_days__("*", "42"), (42,))

    def test_parse_hours_or_days_nothing(self):
        # empty string should refer to the default
        self.assertEqual(cimon.__parse_hours_or_days__("", "42"), (42,))

    def test_parse_hours_or_days_minus_2_to_1(self):
        # fails because of split, that is OK
        self.assertRaises(ValueError, cimon.__parse_hours_or_days__,"-2-1", None)

    def test_parse_hours_or_days_minus_3(self):
        # fails because of split, that is OK
        self.assertRaises(ValueError, cimon.__parse_hours_or_days__,"-3", None)

    def test_parse_hours_or_days_1_to_3_to_5(self):
        # fails because of split into 3
        self.assertRaises(ValueError,cimon.__parse_hours_or_days__,"1-3-5", "42")

    def test_is_operating_hour(self):
        c = Cimon(operating_hours = tuple(range(6,22)),
                  operating_days = tuple(range(0,5)))
        self.assertTrue(c.is_operating(datetime(2016, 5, 12, 12, 44, 57)))

    def test_is_operating_hour_59(self):
        c = Cimon(operating_hours = tuple(range(6,22)),
                  operating_days = tuple(range(0,5)))
        self.assertTrue(c.is_operating(datetime(2016, 5, 12, 21, 59, 59)))

    def test_is_operating_hour_00(self):
        c = Cimon(operating_hours = tuple(range(6,22)),
                  operating_days = tuple(range(0,5)))
        self.assertTrue(c.is_operating(datetime(2016, 5, 12, 6, 00, 00)))

    def test_is_not_operating_hour(self):
        c = Cimon(operating_hours = tuple(range(6,12)),
                  operating_days = (0,1,2,3,4))
        self.assertFalse(c.is_operating(datetime(2016, 5, 12, 12, 44, 57)))

    def test_is_not_operating_day(self):
        c = Cimon(operating_hours = tuple(range(0,24)),
                  operating_days = (0, 1, 2))
        self.assertFalse(c.is_operating(datetime(2016, 5, 12, 12, 44, 57)))

    def test_is_not_operating_hour_59(self):
        c = Cimon(operating_hours = tuple(range(6,22)),
                  operating_days = tuple(range(0,5)))
        self.assertFalse(c.is_operating(datetime(2016, 5, 12, 5, 59, 59)))

    def test_is_not_operating_hour_00(self):
        c = Cimon(operating_hours = tuple(range(6,22)),
                  operating_days = tuple(range(0,5)))
        self.assertFalse(c.is_operating(datetime(2016, 5, 12, 22, 00, 00)))

    def test_sec_to_next_operating_0(self):
        # is operating hour and operating day
        c = Cimon(operating_hours = tuple(range(0,24)),
        operating_days = tuple(range(0,5)))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 12, 44, 57)), 0)

    def test_sec_to_next_operating_next_day_00(self):
        # thursday 00:00:00, but has to wait until friday 00:00:00
        c = Cimon(operating_hours = tuple(range(0,24)),
                  operating_days = (4,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 00, 00, 00)), 24*60*60)

    def test_sec_to_next_operating_next_day_12(self):
        # thursday 12:00:00, but has to wait until friday 00:00:00
        c = Cimon(operating_hours = tuple(range(0,24)),
                  operating_days = (4,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 12, 00, 00)), 12*60*60)

    def test_sec_to_next_operating_same_day_16(self):
        # thursday 12:00:00, but has to wait until 16:00:00
        c = Cimon(operating_hours = (16,),
                  operating_days = (3,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 12, 00, 00)), 4*60*60)

    def test_sec_to_next_operating_same_day_16_mins_secs(self):
        # thursday 12:07:42, but has to wait until 16:00:00
        c = Cimon(operating_hours = (16,),
                  operating_days = (3,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 12, 7, 42)), 4*60*60 - 7*60 - 42)

    def test_sec_to_next_operating_next_day_12_mins_secs(self):
        # thursday 12:07:42, but has to wait until friday 00:00:00
        c = Cimon(operating_hours = tuple(range(0,24)),
                  operating_days = (4,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 12, 7, 42)), 12*60*60 - 7*60 - 42)

    def test_sec_to_next_operating_next_day_12_6_mins_secs(self):
        # thursday 12:07:42, but has to wait until friday 06:00:00
        c = Cimon(operating_hours = tuple(range(6,22)),
                  operating_days = (4,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 12, 7, 42)), 18*60*60 - 7*60 - 42)

    def test_sec_to_next_operating_rollover_day(self):
        # rollover: thursday 00:00:00, but has to wait until monday 00:00:00
        c = Cimon(operating_hours = tuple(range(0,24)),
                  operating_days = (0,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 00, 00, 00)), 4*24*60*60)

    def test_sec_to_next_operating_12__6_mins_secs_rollover_day(self):
        # rollover: thursday 12:07:42, but has to wait until tuesday 00:00:00
        c = Cimon(operating_hours = tuple(range(6,22)),
                  operating_days = (1,))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 5, 12, 12, 7, 42)), 4*24*60*60 + 6*60*60 + 11*60*60 + 52*60 + 18)

    def test_sec_to_next_operating_rollover_day_weekend(self):
        # rollover: sunday 21:00:00, but has to wait until monday 06:00:00
        c = Cimon(operating_hours = tuple(range(6,21)),
                  operating_days = tuple(range(0,4)))
        self.assertEqual(c.sec_to_next_operating(datetime(2016, 8, 28, 21, 00, 00)), (3+6)*60*60)

class CimonConfigurationTests(TestCase):

    def test_configure_file(self):
        c = cimon.configure_from_yaml_file("%s/testdata/cimon_rotating.yaml" % os.path.dirname(__file__))
        self.assertEqual(len(c.collectors), 1)
        self.assertEqual(len(c.outputs), 1)
        self.assertEqual(c.polling_interval_sec, 10)
        self.assertEqual(type(c.collectors[0]).__name__, "RotatingBuildCollector")
        self.assertEqual(type(c.outputs[0]).__name__, "ConsoleOutput")

    def test_configure_file_invalid_yaml_star(self):
        with self.assertRaises(yaml.YAMLError):
            cimon.configure_from_yaml_file("%s/testdata/cimon_invalid_yaml_star.yaml" % os.path.dirname(__file__))

    def test_configure_file_invalid_yaml_no_collector(self):
        with self.assertRaises(yaml.YAMLError):
            cimon.configure_from_yaml_file("%s/testdata/cimon_invalid_yaml_no_collector.yaml" % os.path.dirname(__file__))

    def test_configure_file_invalid_yaml_invalid_list_entry(self):
        with self.assertRaises(yaml.YAMLError):
            cimon.configure_from_yaml_file("%s/testdata/cimon_invalid_yaml_invalid_list_entry.yaml" % os.path.dirname(__file__))

    def test_configure_unkonwn_collector(self):
        with self.assertRaises(ImportError):
            cimon.configure_from_dict({"pollingIntervalSec" : 42, "collector" : [{"implementation" : "gibtsgarnicht"}], "output" : [{"implementation" : "consoleoutput"}]}, None)

    def test_configure_unkonwn_output(self):
        with self.assertRaises(ImportError):
            cimon.configure_from_dict({"pollingIntervalSec" : 42, "collector" : [{"implementation" : "rotatingcollector"}], "output" : [{"implementation" : "gibtsgarnicht"}]}, None)

    def test_configure_no_polling_interval(self):
        with self.assertRaises(KeyError):
            cimon.configure_from_dict({ "collector" : [{"implementation" : "rotatingcollector"}], "output" : [{"implementation" : "consoleoutput"}] }, None)

    def test_configure_no_collectors(self):
        with self.assertRaises(KeyError):
            cimon.configure_from_dict({"pollingIntervalSec" : 42, "output" : [{"implementation" : "consoleoutput"}]}, None)

    def test_configure_no_output(self):
        with self.assertRaises(KeyError):
            cimon.configure_from_dict({"pollingIntervalSec" : 42, "collector" : [{"implementation" : "rotatingcollector"}]}, None)

    def test_configure_empty_collector_list(self):
        with self.assertRaises(ValueError):
            cimon.configure_from_dict({"pollingIntervalSec" : 42, "collector" : [], "output" : [{"implementation" : "rotatingcollector"}]}, None)

    def test_configure_empty_output_list(self):
        with self.assertRaises(ValueError):
            cimon.configure_from_dict({"pollingIntervalSec" : 42, "collector" : [{"implementation" : "rotatingcollector"}], "output" : []}, None)

    def test_configure_collector_in_output(self):
        with self.assertRaises(AttributeError):
            cimon.configure_from_dict({ "pollingIntervalSec" : 42,  "collector" : [{"implementation" : "rotatingcollector"}], "output" : [{"implementation" : "rotatingcollector"}] }, None)

    def test_configure_output_in_collector(self):
        with self.assertRaises(AttributeError):
            cimon.configure_from_dict({ "pollingIntervalSec" : 42,  "collector" : [{"implementation" : "consoleoutput"}], "output" : [{"implementation" : "consoleoutput"}] }, None)

    def test_configure_other_module_in_collector(self):
        with self.assertRaises(AttributeError):
            cimon.configure_from_dict({ "pollingIntervalSec" : 42,  "collector" : [{"implementation" : "configutil"}], "output" : [{"implementation" : "consoleoutput"}] }, None)

    def test_configure_other_module_in_output(self):
        with self.assertRaises(AttributeError):
            cimon.configure_from_dict({ "pollingIntervalSec" : 42,  "collector" : [{"implementation" : "rotatingcollector"}], "output" : [{"implementation" : "configutil"}] }, None)

if __name__ == '__main__':
    main()