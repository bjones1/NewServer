# **********************
# |docname| - Unit tests
# **********************
# .. contents::
#
# Imports
# =======
# These are listed in the order prescribed by `PEP 8
# <http://www.python.org/dev/peps/pep-0008/#imports>`_.
#
# Standard library
# ----------------
from unittest.mock import patch
from contextlib import contextmanager
from datetime import datetime, timedelta

# Third-party imports
# -------------------
import pytest

# Local imports
# -------------
# The ``app`` import is required for the fixtures to work.
from base_test import BaseTest, app, LoginContext, url_joiner, result_remove_usual
from runestone.book_server.server import book_server
from runestone.api.endpoints import api, generic_validator, sql_validator, RequestValidationFailure
from runestone.model import db, Courses, Useinfo, TimedExam, IdMixin, Web2PyBoolean, MchoiceAnswers


# Utilities
# =========
# The common path prefix for testing the server: sp (for server path).
def sp(_str='', **kwargs):
    return url_joiner(book_server.url_prefix, _str, **kwargs)
# Same for the book API: ap (api path)
def ap(_str='', **kwargs):
    return url_joiner(api.url_prefix, _str, **kwargs)


# Server tests
# ============
class TestRunestoneServer(BaseTest):
    # Check the root path view. This is fairly pointless, since this is a temporary page anyway.
    def test_1(self):
        self.must_login(sp())
        with self.login_context:
            self.get_valid(sp(), b'Hello World!', follow_redirects=True)

    # Make sure the 404 page works.
    def test_2(self):
        self.get_invalid('xxx.html')

    # Check that accessing a book via a child course works.
    def test_3(self):
        # Make sure this requires a login.
        url = sp('test_child_course1/foo.html')
        self.must_login(url)

        mock_render_patch = patch('runestone.book_server.server.render_template', return_value='')
        with self.login_context:
            with mock_render_patch as mock_render:
                # When logged in, everything works.
                self.get_valid(url)
            # When not logged in, a login should be requested.
            self.must_login(url)
            mock_render.assert_called_once_with('test_base_course/foo.html', basecourse='test_base_course', login_required='true', python3='true')

        # Check that flags are passed (login_required and python3 are different). Check that no login is needed.
        with mock_render_patch as mock_render:
            self.get_valid(sp('test_child_course2/foo.html'))
            mock_render.assert_called_once_with('test_base_course/foo.html', basecourse='test_base_course', login_required='false', python3='false')

    # Check that static assets are passed through.
    def test_4(self):
        with self.login_context:
            with patch('runestone.book_server.server.send_from_directory', return_value='') as mock_send_from_directory:
                self.get_valid(sp('test_child_course1/_static/foo.css'))
                # Check only the second arg. Note that ``call_args`` `returns <https://docs.python.org/3/library/unittest.mock.html#calls-as-tuples>`_ ``(args, kwargs)``.
                assert mock_send_from_directory.call_args[0][1] == 'test_base_course/_static/foo.css'

                self.get_valid(sp('test_child_course1/_images/foo.png'))
                assert mock_send_from_directory.call_args[0][1] == 'test_base_course/_images/foo.png'


# API tests
# =========
class TestRunestoneApi(BaseTest):
# hsblog
# ------
    hsblog = 'hsblog'
    common_params = dict(
        div_id='test_div_id',
        course='test_child_course1'
    )

    # Check the consistency of values put in Useinfo.
    def test_1(self):
        with self.login_context:
            self.get_valid_json(ap(
                self.hsblog,
                act=1,
                event='mChoice',
                time=5,
                answer='whatever',
                correct='F',
                **self.common_params
            ), dict(
                log=True,
                is_authenticated=True,
            ))
            # Check the timestamp.
            assert (Useinfo[self.username].timestamp.q.scalar() - datetime.now()) < timedelta(seconds=2)
            # Check selected columns of the database record. (Omit the id and timestamp).
            results = result_remove_usual(Useinfo)
            assert results == [dict(
                sid=self.username,
                act='1',
                div_id='test_div_id',
                event='mChoice',
                course_id='test_child_course1',
            )]

    # Check that unauthenticed access produces a consistent sid.
    def test_2(self):
        def go(is_auth=False):
            self.get_valid_json(ap(
                self.hsblog,
                act='xxx',
                event='mChoice',
                answer='yyy',
                correct='T',
                **self.common_params
            ), dict(
                log=True,
                is_authenticated=is_auth,
            ))
        go()
        go()
        r = db.session.Useinfo.sid.q.all()
        assert len(r) == 2
        assert r[0] == r[1]

        # If this user logs in, then make sure the sid is updated. There should now to be 3 log entries, all with sid=username.
        with self.login_context:
            go(True)
        assert Useinfo[self.username].q.count() == 3

    # Check that invalid parameters return an error.
    def test_2_1(self):
        # Unknown course.
        self.get_valid_json(ap(
            self.hsblog,
            act='xxx',
            course='xxx',
        ), dict(
            log=False,
            is_authenticated=False,
            error='Unknown course xxx.',
        ))

        # Undefined course.
        self.get_valid_json(ap(
            self.hsblog,
            act='xxx',
        ), dict(
            log=False,
            is_authenticated=False,
            error='Missing argument course.',
        ))

        # Undefined event.
        with self.login_context:
            self.get_valid_json(ap(
                self.hsblog,
                act='xxx',
                **self.common_params
            ), dict(
                log=False,
                is_authenticated=True,
                error='Missing argument event.',
            ))

            self.get_valid_json(ap(
                self.hsblog,
                act='xxx',
                div_id='yyy',
                course='test_child_course1',
            ), dict(
                log=False,
                is_authenticated=True,
                error='Unknown div_id yyy.',
            ))

        # Strings that are too long for a column.
        self.get_valid_json(ap(
            self.hsblog,
            event='x'*600,
            **self.common_params
        ), dict(
            log=False,
            is_authenticated=False,
            error='Argument event length 600 exceeds the maximum length of 512.',
        ))
        self.get_valid_json(ap(
            self.hsblog,
            event='xxx',
            act='x'*600,
            **self.common_params
        ), dict(
            log=False,
            is_authenticated=False,
            error='Argument act length 600 exceeds the maximum length of 512.',
        ))

    # Verify that the timestamp of the latest row is recent.
    def check_timestamp(self,
        # The model class to check. It must have a column named ``timestamp``.
        model):

        assert (model[model.sid == self.username].timestamp.q.first()[0] - datetime.now()) < timedelta(seconds=2)

    # Check timed exam entries.
    def test_3(self):
        def go(act, log, auth=True):
            self.get_valid_json(
                ap(
                    self.hsblog,
                    act=act,
                    event='timedExam',
                    correct=1,
                    incorrect=2,
                    skipped=3,
                    time=4,
                    **self.common_params
                ), dict(
                    log=log,
                    is_authenticated=auth,
                )
            )
        # No entry - not logged in.
        go('reset', True, False)
        with self.login_context:
            # Invalid act.
            go('xxx', False)
            # Valid flavors
            go('reset', True)
            go('finish', True)
            # Don't provide all the parameters.
            self.get_valid_json(
                ap(
                    self.hsblog,
                    act='reset',
                    event='timedExam',
                    **self.common_params
                ), dict(
                    log=False,
                    is_authenticated=True,
                    error='Missing argument correct.',
                )
            )

        # Check the timestamp.
        self.check_timestamp(TimedExam)

        # Check the results.
        results = result_remove_usual(TimedExam)
        common_items = dict(
            sid=self.username,
            course_name='test_child_course1',
            correct=1,
            incorrect=2,
            skipped=3,
            time_taken=4,
            div_id='test_div_id',
        )
        assert results == [
            dict(
                reset=True,
                **common_items
            ), dict(
                reset=None,
                **common_items,
            )
        ]

    # Check generic_validator.
    def test_4(self):
        # Create a `mock request_context <http://flask.pocoo.org/docs/0.12/testing/#other-testing-tricks>`_ with no arguments.
        with app.test_request_context(ap(self.hsblog)):
            with pytest.raises(RequestValidationFailure) as exc_info:
                generic_validator('param1', None, '')
            assert exc_info.value.args[0] == 'Missing argument param1.'

            # Check default value.
            assert generic_validator('param1', None, '', 1) == 1

        # Check validation.
        with app.test_request_context(ap(self.hsblog, param1='xxx')):
            with pytest.raises(RequestValidationFailure) as exc_info:
                # Return an error as a string.
                def test_validator(arg):
                    assert arg == 'xxx'
                    return False
                generic_validator('param1', test_validator, 'yyy')

                # Raise an error using a formatting function.
                def test_exception_func(arg):
                    assert arg == 'xxx'
                    return 'yyy'
                generic_validator('param1', test_validator, test_exception_func)
            assert exc_info.value.args[0] == 'yyy'

    # Check SQL validator.
    def test_5(self):
        class ModelForTesting(db.Model, IdMixin):
            test_string = db.Column(db.String(10))
            test_bool = db.Column(Web2PyBoolean)
            test_int = db.Column(db.Integer)

        # Create generic test functions.
        def go(test_str, column):
            with app.test_request_context(ap(self.hsblog, param1=test_str)):
                return sql_validator('param1', column)

        def exception_go(test_str, column):
            with app.test_request_context(ap(self.hsblog, param1=test_str)):
                with pytest.raises(RequestValidationFailure) as exc_info:
                    sql_validator('param1', column)
                return exc_info.value.args[0]

        # **Test with a String column**
        with app.test_request_context(ap(self.hsblog)):
            # Test missing argument.
            with pytest.raises(RequestValidationFailure) as exc_info:
                sql_validator('param1', ModelForTesting.test_string)
            assert exc_info.value.args[0] == 'Missing argument param1.'

            # Check default value.
            assert sql_validator('param1', ModelForTesting.test_string, '1') == '1'

        def go_str(test_str):
            assert go(test_str, ModelForTesting.test_string) == test_str
        # Test with the max length string and an empty string.
        go_str('x'*10)
        go_str('')

        # Test with an over-length string.
        assert exception_go('x'*11, ModelForTesting.test_string) == 'Argument param1 length 11 exceeds the maximum length of 10.'

        # **Test with a Web2PyBoolean column**
        #
        # Assume missing/default args work (tested in String above).
        def go_bool(bool_str):
            return go(bool_str, ModelForTesting.test_bool)
        assert go_bool('true') is True
        assert go_bool('T') is True
        assert go_bool('false') is False
        assert go_bool('F') is False
        assert go_bool('') is None
        assert exception_go('xxx', ModelForTesting.test_bool) == 'Argument param1 supplied an invalid boolean value of xxx.'

        # **Test with an Integer column***
        #
        # Assume missing/default args work (tested in String above).
        def go_int(int_str):
            return go(int_str, ModelForTesting.test_int)
        assert go_int('-10') == -10
        assert go_int('10') == 10
        assert go_int('0') == 0
        assert exception_go('xxx', ModelForTesting.test_int) == 'Unable to convert argument param1 to an integer.'

    # Test multiple choice questions.
    def test_6(self):
        def go(answer, correct, auth=True):
            self.get_valid_json(
                ap(
                    self.hsblog,
                    act='',
                    event='mChoice',
                    answer=answer,
                    correct=correct,
                    **self.common_params
                ), dict(
                    log=True,
                    is_authenticated=auth,
                )
            )

            return result_remove_usual(MchoiceAnswers)

        wrong_answer = 'A, B'
        # An unauthenicated submission won't save the answer.
        assert go(wrong_answer, 'F', False) == []

        # Submit an incorrect answer.
        wrong_results = dict(
            answer=wrong_answer,
            correct=False,
            **self.common_results
        )
        with self.login_context:
            assert go(wrong_answer, 'F') == [wrong_results]
        self.check_timestamp(MchoiceAnswers)

        # Submit a correct answer. Now, there are two answers.
        correct_answer = 'B, C'
        correct_results = dict(
            answer=correct_answer,
            correct=True,
            **self.common_results
        )
        all_results = [wrong_results, correct_results]
        with self.login_context:
            assert go(correct_answer, 'T') == all_results
        self.check_timestamp(MchoiceAnswers)

        # Submit a wrong answer. Nothing should be added.
        with self.login_context:
            assert go(wrong_answer, 'F') == all_results


# Web2PyBoolean tests
# ===================
class TestWeb2PyBoolean(BaseTest):
    @contextmanager
    def manual_write_bool(self, bool_):
        # Change a True/False to 'T' or 'F'. Leave None as is.
        if bool_ is True:
            bool_ = 'T'
        elif bool_ is False:
            bool_ = 'F'
        else:
            assert bool_ is None

        db.engine.execute(db.text("insert into courses (course_name, python3) values ('bool_test', :bool_)"), bool_=bool_)
        yield
        db.engine.execute(db.text("delete from courses where course_name='bool_test';"))

    @contextmanager
    def orm_write_bool(self, bool_):
        db.session.add(Courses(course_name='bool_test', python3=bool_))
        db.session.commit()
        yield
        for _ in Courses['bool_test']:
            db.session.delete(_)
        db.session.commit()

    def manual_read_bool(self):
        result = db.engine.execute(db.text("select python3 from courses where course_name='bool_test'")).fetchall()
        assert len(result) == 1
        assert len(result[0].items()) == 1
        return result[0][0]

    def orm_read_bool(self):
        return Courses['bool_test'].python3.q.scalar()

    # Test that web2py boolean values are read back correctly from the database.
    def test_1(self):
        # Manually write values to the database, then read them back.
        with self.manual_write_bool(True):
            assert self.orm_read_bool() is True
        with self.manual_write_bool(False):
            assert self.orm_read_bool() is False
        with self.manual_write_bool(None):
            assert self.orm_read_bool() is None

    # Test that web2py boolean values are written correctly to the database.
    def test_2(self):
        # Write a value, then manually query the result.
        with self.orm_write_bool(True):
            assert self.manual_read_bool() == 'T'
        with self.orm_write_bool(False):
            assert self.manual_read_bool() == 'F'
        with self.orm_write_bool(None):
            assert self.manual_read_bool() is None
