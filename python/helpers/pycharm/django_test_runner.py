from tcunittest import TeamcityTestRunner, TeamcityTestResult
from tcmessages import TeamcityServiceMessages
from pycharm_run_utils import adjust_django_sys_path
adjust_django_sys_path()

from django.conf import settings

if hasattr(settings, "TEST_RUNNER") and "NoseTestSuiteRunner" in settings.TEST_RUNNER:
    from nose_utils import TeamcityNoseRunner

from django.test.testcases import TestCase
from django import VERSION
try:
    from django.utils import unittest
except ImportError:
    import unittest

def get_test_suite_runner():
  if hasattr(settings, "TEST_RUNNER"):
    from django.test.utils import get_runner

    class TempSettings:
      TEST_RUNNER = settings.TEST_RUNNER

    return get_runner(TempSettings)

try:
  from django.test.simple import DjangoTestSuiteRunner
  from inspect import isfunction

  SUITE_RUNNER = get_test_suite_runner()
  if isfunction(SUITE_RUNNER):
    import sys

    sys.stderr.write(
      "WARNING: TEST_RUNNER variable is ignored. PyCharm test runner supports "
      "only class-like TEST_RUNNER valiables. Use Tools->run manage.py tasks.\n")
    SUITE_RUNNER = None
  BaseSuiteRunner = SUITE_RUNNER or DjangoTestSuiteRunner

  class BaseRunner(TeamcityTestRunner, BaseSuiteRunner):
    def __init__(self, stream=sys.stdout, **options):
      TeamcityTestRunner.__init__(self, stream)
      BaseSuiteRunner.__init__(self)

except ImportError:
  # for Django <= 1.1 compatibility
  class BaseRunner(TeamcityTestRunner):
    def __init__(self, stream=sys.stdout, **options):
      TeamcityTestRunner.__init__(self, stream)


def strclass(cls):
  if not cls.__name__:
    return cls.__module__
  return "%s.%s" % (cls.__module__, cls.__name__)

class DjangoTeamcityTestResult(TeamcityTestResult):
  def __init__(self, *args, **kwargs):
    super(DjangoTeamcityTestResult, self).__init__()

  def _getSuite(self, test):
    if hasattr(test, "suite"):
      suite = strclass(test.suite)
      suite_location = test.suite.location
      location = test.suite.abs_location
      if hasattr(test, "lineno"):
        location = location + ":" + str(test.lineno)
      else:
        location = location + ":" + str(test.test.lineno)
    else:

      suite = strclass(test.__class__)
      suite_location = "django_testid://" + suite
      location = "django_testid://" + str(test.id())

    return (suite, location, suite_location)


class DjangoTeamcityTestRunner(BaseRunner):
  def __init__(self, stream=sys.stdout, **options):
    super(DjangoTeamcityTestRunner, self).__init__(stream)

  def _makeResult(self, **kwargs):
    return DjangoTeamcityTestResult(self.stream, **kwargs)

  def build_suite(self, *args, **kwargs):
    EXCLUDED_APPS = getattr(settings, 'TEST_EXCLUDE', [])
    suite = super(DjangoTeamcityTestRunner, self).build_suite(*args, **kwargs)
    if not args[0] and not getattr(settings, 'RUN_ALL_TESTS', False):
      tests = []
      for case in suite:
        pkg = case.__class__.__module__.split('.')[0]
        if pkg not in EXCLUDED_APPS:
          tests.append(case)
      suite._tests = tests
    return suite

  def run_suite(self, suite, **kwargs):
    if hasattr(settings, "TEST_RUNNER") and "NoseTestSuiteRunner" in settings.TEST_RUNNER:
      from django_nose.plugin import DjangoSetUpPlugin, ResultPlugin
      from django_nose.runner import _get_plugins_from_settings
      from nose.plugins.manager import PluginManager
      from nose.config import Config
      import nose

      config = Config(plugins=PluginManager())
      config.plugins.loadPlugins()
      result_plugin = ResultPlugin()
      config.plugins.addPlugin(DjangoSetUpPlugin(self))
      config.plugins.addPlugin(result_plugin)
      for plugin in _get_plugins_from_settings():
        config.plugins.addPlugin(plugin)

      nose.core.TestProgram(argv=suite, exit=False,
        testRunner=TeamcityNoseRunner(config=config))
      return result_plugin.result
    else:
      return TeamcityTestRunner.run(self, suite, **kwargs)

  def run_tests(self, test_labels, extra_tests=None, **kwargs):
    if hasattr(settings, "TEST_RUNNER") and "NoseTestSuiteRunner" in settings.TEST_RUNNER:
      return super(DjangoTeamcityTestRunner, self).run_tests(test_labels,
        extra_tests)
    return super(DjangoTeamcityTestRunner, self).run_tests(test_labels,
      extra_tests, **kwargs)


def partition_suite(suite, classes, bins):
  """
  Partitions a test suite by test type.

  classes is a sequence of types
  bins is a sequence of TestSuites, one more than classes

  Tests of type classes[i] are added to bins[i],
  tests with no match found in classes are place in bins[-1]
  """
  for test in suite:
    if isinstance(test, unittest.TestSuite):
      partition_suite(test, classes, bins)
    else:
      for i in range(len(classes)):
        if isinstance(test, classes[i]):
          bins[i].addTest(test)
          break
      else:
        bins[-1].addTest(test)


def reorder_suite(suite, classes):
  """
  Reorders a test suite by test type.

  classes is a sequence of types

  All tests of type clases[0] are placed first, then tests of type classes[1], etc.
  Tests with no match in classes are placed last.
  """
  class_count = len(classes)
  bins = [unittest.TestSuite() for i in range(class_count + 1)]
  partition_suite(suite, classes, bins)
  for i in range(class_count):
    bins[0].addTests(bins[i + 1])
  return bins[0]


def run_the_old_way(extra_tests, kwargs, test_labels, verbosity):
    from django.test.simple import build_suite, build_test, get_app, get_apps, \
        setup_test_environment, teardown_test_environment

    setup_test_environment()
    settings.DEBUG = False
    suite = unittest.TestSuite()
    if test_labels:
        for label in test_labels:
            if '.' in label:
                suite.addTest(build_test(label))
            else:
                app = get_app(label)
                suite.addTest(build_suite(app))
    else:
        for app in get_apps():
            suite.addTest(build_suite(app))
    for test in extra_tests:
        suite.addTest(test)
    suite = reorder_suite(suite, (TestCase,))
    old_name = settings.DATABASE_NAME
    from django.db import connection

    connection.creation.create_test_db(verbosity, autoclobber=False)
    result = DjangoTeamcityTestRunner().run(suite, **kwargs)
    connection.creation.destroy_test_db(old_name, verbosity)
    teardown_test_environment()
    return len(result.failures) + len(result.errors)


def run_tests(test_labels, verbosity=1, interactive=False, extra_tests=[],
              **kwargs):
  """
  Run the unit tests for all the test labels in the provided list.
  Labels must be of the form:
   - app.TestClass.test_method
      Run a single specific test method
   - app.TestClass
      Run all the test methods in a given class
   - app
      Search for doctests and unittests in the named application.

  When looking for tests, the test runner will look in the models and
  tests modules for the application.

  A list of 'extra' tests may also be provided; these tests
  will be added to the test suite.

  Returns the number of tests that failed.
  """
  TeamcityServiceMessages(sys.stdout).testMatrixEntered()
  if VERSION[1] > 1:
    return DjangoTeamcityTestRunner().run_tests(test_labels,
      extra_tests=extra_tests, **kwargs)

  return run_the_old_way(extra_tests, kwargs, test_labels, verbosity)
