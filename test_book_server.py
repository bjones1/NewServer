# ********************************
# test_book_server.py - Unit tests
# ********************************
# Invocation:
#
# - To run all tests: ``pytest``.
#
# Imports
# =======
# These are listed in the order prescribed by `PEP 8
# <http://www.python.org/dev/peps/pep-0008/#imports>`_.
#
# Standard library
# ----------------
import json

# Third-party imports
# -------------------
import pytest

# Local imports
# -------------
from runestone import create_app, db, user_datastore

# Tests
# =====
# Create a testing application.
app = create_app('testing')

# Data
# ----
# Creates some fake data which the tests use.
# Create test data.
def create_test_data():
    user_datastore.create_user(email='brad@test.user', password='grouplens')
    db.session.commit()

# Fixtures
# --------
# Set up the database for the test session. Do this just once for all tests, rather than every test (module scope).
@pytest.fixture(scope='module')
def test_db():
    # _`test_client`: the `test client <http://flask.pocoo.org/docs/0.11/api/#flask.Flask.test_client>`_ to request pages from.
    test_client = app.test_client()
    with app.app_context():
        db.create_all()

    return test_client

# Define `per-function setup and teardown <http://doc.pytest.org/en/latest/fixture.html#fixture-finalization-executing-teardown-code>`_ which places test data in an already existing database, then removes all data from the database when the test finishes.
@pytest.fixture()
def test_client(test_db, request):
    # Setup
    with app.app_context():
        create_test_data()

    def teardown():
        with app.app_context():
            # Teardown. Adapted from http://stackoverflow.com/a/5003705. A simple db.drop_all() works, but doubles test time. This should remove all data, but keep the schema.
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(table.delete())
            db.session.commit()
    request.addfinalizer(teardown)

    return test_db


# Utilities
# ---------
# Define a `context manger <https://docs.python.org/3/reference/datamodel.html#context-managers>`_ which sandwiches its body with a ``login``/``logout``.
class LoginContext:
    def __init__(self, test_class, username, *args):
        self.test_class = test_class
        self.username = username
        self.args = args

    def __enter__(self):
        return self.test_class.login(self.username, *self.args)

    def __exit__(self, exc_type, exc_value, traceback):
        self.test_class.logout()

# Apply these fixes to every test `automatically <https://docs.pytest.org/en/latest/fixture.html#using-fixtures-from-classes-modules-or-projects>`_.
@pytest.mark.usefixtures("test_client_")
# Group everything in a class, so it's easy to share the test_client_.
class TestRunestoneServer:
    # Create a fixture which stores the test_client in ``self``.
    @pytest.fixture()
    def test_client_(self, test_client):
        self.test_client = test_client

    # _`get_check`: Get a web page, checking its returned status code and optionally its contents.
    def get_check(self,
        # _`url`: The bare URL to reqeust (so that ``/`` refers to the root of the web site).
        url,
        # The expected `status code <http://flask.pocoo.org/docs/0.11/api/#flask.Response.status_code>`_ returned by the web server. See https://en.wikipedia.org/wiki/List_of_HTTP_status_codes for a list of all codes.
        expected_status,
        # _`expected_response_phrase`: A phrase which must be ``in`` the text returned. The type must be ``bytes``; the default argument of ``b''`` skips this check.
        expected_response_phrase=b'',
        # _`kwargs`: Any additional keyword arguments to pass to `test_client.get <http://werkzeug.pocoo.org/docs/0.11/test/#werkzeug.test.Client.get>`_, such as ``follow_redirects=True``.
        **kwargs):

        # The call to `test_client.get`_ returns a `response object <http://flask.pocoo.org/docs/0.11/api/#response-objects>`_.
        rv = self.test_client.get(url, **kwargs)
        try:
            # Check the `status code`_ and the `data <http://flask.pocoo.org/docs/0.11/api/#flask.Response.data>`_.
            assert rv.status_code == expected_status
            assert expected_response_phrase in rv.data
        except AssertionError:
            # On a test failure, save the resulting web page for debug purposes.
            with open('tmp.html', 'wb') as f:
                f.write(rv.data)
            raise
        return rv

    # _`get_valid`: Get a web page, verifying the `status code`_ was 200 (OK). This function returns the value produced by get_check_.
    def get_valid(self,
      # See url_.
      url,
      # Optionally provide the expected_response_phrase_.
      *args,
      # See kwargs_.
      **kwargs):

        return self.get_check(url, 200, *args, **kwargs)

    # After get_valid_, check that the returned data is the expected, JSON-formatted dict. This function returns the value produced by get_valid_.
    def get_valid_json(self,
      # See url_.
      url,
      # The expected response dictionary produce by interpreting the response data as UTF-8 encoded JSON.
      expected_response_dict,
      # See kwargs_.
      **kwargs):

        rv = self.get_valid(url, **kwargs)
        assert json.loads(str(rv.data, encoding='utf-8')) == expected_response_dict
        return rv

    # Get a web page, verifying the `status code`_ was 404 (not found). This function returns the value produced by get_check_.
    def get_invalid(self,
      # See url_.
      url,
      # See kwargs_.
      **kwargs):

        return self.get_check(url, 404, b'The requested URL was not found on the server.',
            **kwargs)

    # Verify that a login with the given username succeeds.
    def login(self, email, password):
        rv = self.test_client.post(app.config['SECURITY_LOGIN_URL'], data=dict(
                email=email,
                password=password,
                remember='y',
            ),
            follow_redirects=True)
        # TODO: Expect the text of a flashed message after a login.
        ##assert b'You have signed in successfully.' in rv.data
        assert rv.status_code == 200
        return rv

    # Verify that a logout succeeds.
    def logout(self):
        return self.get_valid(app.config['SECURITY_LOGOUT_URL'],
            b'Please log in to access this page.', follow_redirects=True)

# Tests
# -----
    # Check the root path view.
    def test_1(self):
        with LoginContext(self, 'brad@test.user', 'grouplens'):
            self.get_valid('/runestone', follow_redirects=True)

    # Make sure the 404 page works.
    def test_2(self):
        self.get_invalid('xxx.html')

    # An example of checking the JSON returned from a URL.
    questions_url = '/book/unsigned_8-_and_16-bit_ops/introduction.s.html/questions'
    def example_test_9(self):
        with LoginContext(self, 'student'):
            self.get_valid_json(self.questions_url,
                           {'define_label': ['foo:', 2, 2, 'correct'],
                            'comment': ['10000', 0, 1, 'Incorrect.']})