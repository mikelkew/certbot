"""Tests for certbot.util."""
import argparse
import errno
import unittest

import mock
import six
from six.moves import reload_module  # pylint: disable=import-error

import certbot.tests.util as test_util
from certbot import errors
from certbot.compat import os
from certbot.compat import filesystem


class RunScriptTest(unittest.TestCase):
    """Tests for certbot.util.run_script."""
    @classmethod
    def _call(cls, params):
        from certbot.util import run_script
        return run_script(params)

    @mock.patch("certbot.util.subprocess.Popen")
    def test_default(self, mock_popen):
        """These will be changed soon enough with reload."""
        mock_popen().returncode = 0
        mock_popen().communicate.return_value = ("stdout", "stderr")

        out, err = self._call(["test"])
        self.assertEqual(out, "stdout")
        self.assertEqual(err, "stderr")

    @mock.patch("certbot.util.subprocess.Popen")
    def test_bad_process(self, mock_popen):
        mock_popen.side_effect = OSError

        self.assertRaises(errors.SubprocessError, self._call, ["test"])

    @mock.patch("certbot.util.subprocess.Popen")
    def test_failure(self, mock_popen):
        mock_popen().communicate.return_value = ("", "")
        mock_popen().returncode = 1

        self.assertRaises(errors.SubprocessError, self._call, ["test"])


class ExeExistsTest(unittest.TestCase):
    """Tests for certbot.util.exe_exists."""

    @classmethod
    def _call(cls, exe):
        from certbot.util import exe_exists
        return exe_exists(exe)

    @mock.patch("certbot.util.os.path.isfile")
    @mock.patch("certbot.util.os.access")
    def test_full_path(self, mock_access, mock_isfile):
        mock_access.return_value = True
        mock_isfile.return_value = True
        self.assertTrue(self._call("/path/to/exe"))

    @mock.patch("certbot.util.os.path.isfile")
    @mock.patch("certbot.util.os.access")
    def test_on_path(self, mock_access, mock_isfile):
        mock_access.return_value = True
        mock_isfile.return_value = True
        self.assertTrue(self._call("exe"))

    @mock.patch("certbot.util.os.path.isfile")
    @mock.patch("certbot.util.os.access")
    def test_not_found(self, mock_access, mock_isfile):
        mock_access.return_value = False
        mock_isfile.return_value = True
        self.assertFalse(self._call("exe"))


class LockDirUntilExit(test_util.TempDirTestCase):
    """Tests for certbot.util.lock_dir_until_exit."""
    @classmethod
    def _call(cls, *args, **kwargs):
        from certbot.util import lock_dir_until_exit
        return lock_dir_until_exit(*args, **kwargs)

    def setUp(self):
        super(LockDirUntilExit, self).setUp()
        # reset global state from other tests
        import certbot.util
        reload_module(certbot.util)

    @mock.patch('certbot.util.logger')
    @mock.patch('certbot.util.atexit_register')
    def test_it(self, mock_register, mock_logger):
        subdir = os.path.join(self.tempdir, 'subdir')
        filesystem.mkdir(subdir)
        self._call(self.tempdir)
        self._call(subdir)
        self._call(subdir)

        self.assertEqual(mock_register.call_count, 1)
        registered_func = mock_register.call_args[0][0]

        from certbot import util
        # Despite lock_dir_until_exit has been called twice to subdir, its lock should have been
        # added only once. So we expect to have two lock references: for self.tempdir and subdir
        self.assertTrue(len(util._LOCKS) == 2)  # pylint: disable=protected-access
        registered_func()  # Exception should not be raised
        # Logically, logger.debug, that would be invoked in case of unlock failure,
        # should never been called.
        self.assertEqual(mock_logger.debug.call_count, 0)


class SetUpCoreDirTest(test_util.TempDirTestCase):
    """Tests for certbot.util.make_or_verify_core_dir."""

    def _call(self, *args, **kwargs):
        from certbot.util import set_up_core_dir
        return set_up_core_dir(*args, **kwargs)

    @mock.patch('certbot.util.lock_dir_until_exit')
    def test_success(self, mock_lock):
        new_dir = os.path.join(self.tempdir, 'new')
        self._call(new_dir, 0o700, False)
        self.assertTrue(os.path.exists(new_dir))
        self.assertEqual(mock_lock.call_count, 1)

    @mock.patch('certbot.util.make_or_verify_dir')
    def test_failure(self, mock_make_or_verify):
        mock_make_or_verify.side_effect = OSError
        self.assertRaises(errors.Error, self._call, self.tempdir, 0o700, False)


class MakeOrVerifyDirTest(test_util.TempDirTestCase):
    """Tests for certbot.util.make_or_verify_dir.

    Note that it is not possible to test for a wrong directory owner,
    as this testing script would have to be run as root.

    """

    def setUp(self):
        super(MakeOrVerifyDirTest, self).setUp()

        self.path = os.path.join(self.tempdir, "foo")
        filesystem.mkdir(self.path, 0o600)

    def _call(self, directory, mode):
        from certbot.util import make_or_verify_dir
        return make_or_verify_dir(directory, mode, strict=True)

    def test_creates_dir_when_missing(self):
        path = os.path.join(self.tempdir, "bar")
        self._call(path, 0o650)
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(filesystem.check_mode(path, 0o650))

    def test_existing_correct_mode_does_not_fail(self):
        self._call(self.path, 0o600)
        self.assertTrue(filesystem.check_mode(self.path, 0o600))

    def test_existing_wrong_mode_fails(self):
        self.assertRaises(errors.Error, self._call, self.path, 0o400)

    def test_reraises_os_error(self):
        with mock.patch.object(filesystem, "makedirs") as makedirs:
            makedirs.side_effect = OSError()
            self.assertRaises(OSError, self._call, "bar", 12312312)


class UniqueFileTest(test_util.TempDirTestCase):
    """Tests for certbot.util.unique_file."""

    def setUp(self):
        super(UniqueFileTest, self).setUp()

        self.default_name = os.path.join(self.tempdir, "foo.txt")

    def _call(self, mode=0o600):
        from certbot.util import unique_file
        return unique_file(self.default_name, mode)

    def test_returns_fd_for_writing(self):
        fd, name = self._call()
        fd.write("bar")
        fd.close()
        with open(name) as f:
            self.assertEqual(f.read(), "bar")

    def test_right_mode(self):
        fd1, name1 = self._call(0o700)
        fd2, name2 = self._call(0o600)
        self.assertTrue(filesystem.check_mode(name1, 0o700))
        self.assertTrue(filesystem.check_mode(name2, 0o600))
        fd1.close()
        fd2.close()

    def test_default_exists(self):
        fd1, name1 = self._call()  # create 0000_foo.txt
        fd2, name2 = self._call()
        fd3, name3 = self._call()

        self.assertNotEqual(name1, name2)
        self.assertNotEqual(name1, name3)
        self.assertNotEqual(name2, name3)

        self.assertEqual(os.path.dirname(name1), self.tempdir)
        self.assertEqual(os.path.dirname(name2), self.tempdir)
        self.assertEqual(os.path.dirname(name3), self.tempdir)

        basename1 = os.path.basename(name2)
        self.assertTrue(basename1.endswith("foo.txt"))
        basename2 = os.path.basename(name2)
        self.assertTrue(basename2.endswith("foo.txt"))
        basename3 = os.path.basename(name3)
        self.assertTrue(basename3.endswith("foo.txt"))

        fd1.close()
        fd2.close()
        fd3.close()


try:
    file_type = file
except NameError:
    import io
    file_type = io.TextIOWrapper  # type: ignore


class UniqueLineageNameTest(test_util.TempDirTestCase):
    """Tests for certbot.util.unique_lineage_name."""

    def _call(self, filename, mode=0o777):
        from certbot.util import unique_lineage_name
        return unique_lineage_name(self.tempdir, filename, mode)

    def test_basic(self):
        f, path = self._call("wow")
        self.assertTrue(isinstance(f, file_type))
        self.assertEqual(os.path.join(self.tempdir, "wow.conf"), path)
        f.close()

    def test_multiple(self):
        items = []
        for _ in six.moves.range(10):
            items.append(self._call("wow"))
        f, name = items[-1]
        self.assertTrue(isinstance(f, file_type))
        self.assertTrue(isinstance(name, six.string_types))
        self.assertTrue("wow-0009.conf" in name)
        for f, _ in items:
            f.close()

    def test_failure(self):
        with mock.patch("certbot.compat.filesystem.open", side_effect=OSError(errno.EIO)):
            self.assertRaises(OSError, self._call, "wow")


class SafelyRemoveTest(test_util.TempDirTestCase):
    """Tests for certbot.util.safely_remove."""

    def setUp(self):
        super(SafelyRemoveTest, self).setUp()

        self.path = os.path.join(self.tempdir, "foo")

    def _call(self):
        from certbot.util import safely_remove
        return safely_remove(self.path)

    def test_exists(self):
        with open(self.path, "w"):
            pass  # just create the file
        self._call()
        self.assertFalse(os.path.exists(self.path))

    def test_missing(self):
        self._call()
        # no error, yay!
        self.assertFalse(os.path.exists(self.path))

    def test_other_error_passthrough(self):
        with mock.patch("certbot.util.os.remove") as mock_remove:
            mock_remove.side_effect = OSError
            self.assertRaises(OSError, self._call)


class SafeEmailTest(unittest.TestCase):
    """Test safe_email."""
    @classmethod
    def _call(cls, addr):
        from certbot.util import safe_email
        return safe_email(addr)

    def test_valid_emails(self):
        addrs = [
            "certbot@certbot.org",
            "tbd.ade@gmail.com",
            "abc_def.jdk@hotmail.museum",
        ]
        for addr in addrs:
            self.assertTrue(self._call(addr), "%s failed." % addr)

    def test_invalid_emails(self):
        addrs = [
            "certbot@certbot..org",
            ".tbd.ade@gmail.com",
            "~/abc_def.jdk@hotmail.museum",
        ]
        for addr in addrs:
            self.assertFalse(self._call(addr), "%s failed." % addr)


class AddDeprecatedArgumentTest(unittest.TestCase):
    """Test add_deprecated_argument."""
    def setUp(self):
        self.parser = argparse.ArgumentParser()

    def _call(self, argument_name, nargs):
        from certbot.util import add_deprecated_argument
        add_deprecated_argument(self.parser.add_argument, argument_name, nargs)

    def test_warning_no_arg(self):
        self._call("--old-option", 0)
        with mock.patch("certbot.util.logger.warning") as mock_warn:
            self.parser.parse_args(["--old-option"])
        self.assertEqual(mock_warn.call_count, 1)
        self.assertTrue("is deprecated" in mock_warn.call_args[0][0])
        self.assertEqual("--old-option", mock_warn.call_args[0][1])

    def test_warning_with_arg(self):
        self._call("--old-option", 1)
        with mock.patch("certbot.util.logger.warning") as mock_warn:
            self.parser.parse_args(["--old-option", "42"])
        self.assertEqual(mock_warn.call_count, 1)
        self.assertTrue("is deprecated" in mock_warn.call_args[0][0])
        self.assertEqual("--old-option", mock_warn.call_args[0][1])

    def test_help(self):
        self._call("--old-option", 2)
        stdout = six.StringIO()
        with mock.patch("sys.stdout", new=stdout):
            try:
                self.parser.parse_args(["-h"])
            except SystemExit:
                pass
        self.assertTrue("--old-option" not in stdout.getvalue())

    def test_set_constant(self):
        """Test when ACTION_TYPES_THAT_DONT_NEED_A_VALUE is a set.

        This variable is a set in configargparse versions < 0.12.0.

        """
        self._test_constant_common(set)

    def test_tuple_constant(self):
        """Test when ACTION_TYPES_THAT_DONT_NEED_A_VALUE is a tuple.

        This variable is a tuple in configargparse versions >= 0.12.0.

        """
        self._test_constant_common(tuple)

    def _test_constant_common(self, typ):
        with mock.patch("certbot.util.configargparse") as mock_configargparse:
            mock_configargparse.ACTION_TYPES_THAT_DONT_NEED_A_VALUE = typ()
            self._call("--old-option", 1)
            self._call("--old-option2", 2)
        self.assertEqual(
            len(mock_configargparse.ACTION_TYPES_THAT_DONT_NEED_A_VALUE), 1)


class EnforceLeValidity(unittest.TestCase):
    """Test enforce_le_validity."""
    def _call(self, domain):
        from certbot.util import enforce_le_validity
        return enforce_le_validity(domain)

    def test_sanity(self):
        self.assertRaises(errors.ConfigurationError, self._call, u"..")

    def test_invalid_chars(self):
        self.assertRaises(
            errors.ConfigurationError, self._call, u"hello_world.example.com")

    def test_leading_hyphen(self):
        self.assertRaises(
            errors.ConfigurationError, self._call, u"-a.example.com")

    def test_trailing_hyphen(self):
        self.assertRaises(
            errors.ConfigurationError, self._call, u"a-.example.com")

    def test_one_label(self):
        self.assertRaises(errors.ConfigurationError, self._call, u"com")

    def test_valid_domain(self):
        self.assertEqual(self._call(u"example.com"), u"example.com")

    def test_input_with_scheme(self):
        self.assertRaises(errors.ConfigurationError, self._call, u"http://example.com")
        self.assertRaises(errors.ConfigurationError, self._call, u"https://example.com")

    def test_valid_input_with_scheme_name(self):
        self.assertEqual(self._call(u"http.example.com"), u"http.example.com")


class EnforceDomainSanityTest(unittest.TestCase):
    """Test enforce_domain_sanity."""

    def _call(self, domain):
        from certbot.util import enforce_domain_sanity
        return enforce_domain_sanity(domain)

    def test_nonascii_str(self):
        self.assertRaises(errors.ConfigurationError, self._call,
                          u"eichh\u00f6rnchen.example.com".encode("utf-8"))

    def test_nonascii_unicode(self):
        self.assertRaises(errors.ConfigurationError, self._call,
                          u"eichh\u00f6rnchen.example.com")

    def test_too_long(self):
        long_domain = u"a"*256
        self.assertRaises(errors.ConfigurationError, self._call,
                          long_domain)

    def test_not_too_long(self):
        not_too_long_domain = u"{0}.{1}.{2}.{3}".format("a"*63, "b"*63, "c"*63, "d"*63)
        self._call(not_too_long_domain)

    def test_empty_label(self):
        empty_label_domain = u"fizz..example.com"
        self.assertRaises(errors.ConfigurationError, self._call,
                          empty_label_domain)

    def test_empty_trailing_label(self):
        empty_trailing_label_domain = u"example.com.."
        self.assertRaises(errors.ConfigurationError, self._call,
                          empty_trailing_label_domain)

    def test_long_label_1(self):
        long_label_domain = u"a"*64
        self.assertRaises(errors.ConfigurationError, self._call,
                          long_label_domain)

    def test_long_label_2(self):
        long_label_domain = u"{0}.{1}.com".format(u"a"*64, u"b"*63)
        self.assertRaises(errors.ConfigurationError, self._call,
                          long_label_domain)

    def test_not_long_label(self):
        not_too_long_label_domain = u"{0}.{1}.com".format(u"a"*63, u"b"*63)
        self._call(not_too_long_label_domain)

    def test_empty_domain(self):
        empty_domain = u""
        self.assertRaises(errors.ConfigurationError, self._call,
                          empty_domain)

    def test_punycode_ok(self):
        # Punycode is now legal, so no longer an error; instead check
        # that it's _not_ an error (at the initial sanity check stage)
        self._call('this.is.xn--ls8h.tld')


class IsWildcardDomainTest(unittest.TestCase):
    """Tests for is_wildcard_domain."""

    def setUp(self):
        self.wildcard = u"*.example.org"
        self.no_wildcard = u"example.org"

    def _call(self, domain):
        from certbot.util import is_wildcard_domain
        return is_wildcard_domain(domain)

    def test_no_wildcard(self):
        self.assertFalse(self._call(self.no_wildcard))
        self.assertFalse(self._call(self.no_wildcard.encode()))

    def test_wildcard(self):
        self.assertTrue(self._call(self.wildcard))
        self.assertTrue(self._call(self.wildcard.encode()))


class OsInfoTest(unittest.TestCase):
    """Test OS / distribution detection"""

    def test_systemd_os_release(self):
        from certbot.util import (get_os_info, get_systemd_os_info,
                                  get_os_info_ua)

        with mock.patch('certbot.compat.os.path.isfile', return_value=True):
            self.assertEqual(get_os_info(
                test_util.vector_path("os-release"))[0], 'systemdos')
            self.assertEqual(get_os_info(
                test_util.vector_path("os-release"))[1], '42')
            self.assertEqual(get_systemd_os_info(os.devnull), ("", ""))
            self.assertEqual(get_os_info_ua(
                test_util.vector_path("os-release")), "SystemdOS")
        with mock.patch('certbot.compat.os.path.isfile', return_value=False):
            self.assertEqual(get_systemd_os_info(), ("", ""))

    def test_systemd_os_release_like(self):
        from certbot.util import get_systemd_os_like

        with mock.patch('certbot.compat.os.path.isfile', return_value=True):
            id_likes = get_systemd_os_like(test_util.vector_path(
                "os-release"))
            self.assertEqual(len(id_likes), 3)
            self.assertTrue("debian" in id_likes)

    @mock.patch("certbot.util.subprocess.Popen")
    def test_non_systemd_os_info(self, popen_mock):
        from certbot.util import (get_os_info, get_python_os_info,
                                     get_os_info_ua)
        with mock.patch('certbot.compat.os.path.isfile', return_value=False):
            with mock.patch('platform.system_alias',
                            return_value=('NonSystemD', '42', '42')):
                self.assertEqual(get_os_info()[0], 'nonsystemd')
                self.assertEqual(get_os_info_ua(),
                                 " ".join(get_python_os_info()))

            with mock.patch('platform.system_alias',
                            return_value=('darwin', '', '')):
                comm_mock = mock.Mock()
                comm_attrs = {'communicate.return_value':
                              ('42.42.42', 'error')}
                comm_mock.configure_mock(**comm_attrs)
                popen_mock.return_value = comm_mock
                self.assertEqual(get_os_info()[0], 'darwin')
                self.assertEqual(get_os_info()[1], '42.42.42')

            with mock.patch('platform.system_alias',
                            return_value=('linux', '', '')):
                with mock.patch('platform.linux_distribution',
                                return_value=('', '', '')):
                    self.assertEqual(get_python_os_info(), ("linux", ""))

                with mock.patch('platform.linux_distribution',
                                return_value=('testdist', '42', '')):
                    self.assertEqual(get_python_os_info(), ("testdist", "42"))

            with mock.patch('platform.system_alias',
                            return_value=('freebsd', '9.3-RC3-p1', '')):
                self.assertEqual(get_python_os_info(), ("freebsd", "9"))

            with mock.patch('platform.system_alias',
                            return_value=('windows', '', '')):
                with mock.patch('platform.win32_ver',
                                return_value=('4242', '95', '2', '')):
                    self.assertEqual(get_python_os_info(),
                                     ("windows", "95"))


class AtexitRegisterTest(unittest.TestCase):
    """Tests for certbot.util.atexit_register."""
    def setUp(self):
        self.func = mock.MagicMock()
        self.args = ('hi',)
        self.kwargs = {'answer': 42}

    @classmethod
    def _call(cls, *args, **kwargs):
        from certbot.util import atexit_register
        return atexit_register(*args, **kwargs)

    def test_called(self):
        self._test_common(os.getpid())
        self.func.assert_called_with(*self.args, **self.kwargs)

    def test_not_called(self):
        self._test_common(initial_pid=-1)
        self.assertFalse(self.func.called)

    def _test_common(self, initial_pid):
        with mock.patch('certbot.util._INITIAL_PID', initial_pid):
            with mock.patch('certbot.util.atexit') as mock_atexit:
                self._call(self.func, *self.args, **self.kwargs)

            # _INITAL_PID must be mocked when calling atexit_func
            self.assertTrue(mock_atexit.register.called)
            args, kwargs = mock_atexit.register.call_args
            atexit_func = args[0]
            atexit_func(*args[1:], **kwargs)


if __name__ == "__main__":
    unittest.main()  # pragma: no cover
