# Copyright 2014 IBM Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy

from tempest import auth
from tempest.common import http
from tempest import config
from tempest import exceptions
from tempest.openstack.common.fixture import mockpatch
from tempest.tests import base
from tempest.tests import fake_config
from tempest.tests import fake_http
from tempest.tests import fake_identity


class BaseAuthTestsSetUp(base.TestCase):
    _auth_provider_class = None
    credentials = {
        'username': 'fake_user',
        'password': 'fake_pwd',
        'tenant_name': 'fake_tenant'
    }

    def _auth(self, credentials, **params):
        """
        returns auth method according to keystone
        """
        return self._auth_provider_class(credentials, **params)

    def setUp(self):
        super(BaseAuthTestsSetUp, self).setUp()
        self.stubs.Set(config, 'TempestConfigPrivate', fake_config.FakeConfig)
        self.fake_http = fake_http.fake_httplib2(return_type=200)
        self.stubs.Set(http.ClosingHttp, 'request', self.fake_http.request)
        self.auth_provider = self._auth(self.credentials)


class TestBaseAuthProvider(BaseAuthTestsSetUp):
    """
    This tests auth.AuthProvider class which is base for the other so we
    obviously don't test not implemented method or the ones which strongly
    depends on them.
    """
    _auth_provider_class = auth.AuthProvider

    def test_check_credentials_is_dict(self):
        self.assertTrue(self.auth_provider.check_credentials({}))

    def test_check_credentials_bad_type(self):
        self.assertFalse(self.auth_provider.check_credentials([]))

    def test_instantiate_with_bad_credentials_type(self):
        """
        Assure that credentials with bad type fail with TypeError
        """
        self.assertRaises(TypeError, self._auth, [])

    def test_auth_data_property(self):
        self.assertRaises(NotImplementedError, getattr, self.auth_provider,
                          'auth_data')

    def test_auth_data_property_when_cache_exists(self):
        self.auth_provider.cache = 'foo'
        self.useFixture(mockpatch.PatchObject(self.auth_provider,
                                              'is_expired',
                                              return_value=False))
        self.assertEqual('foo', getattr(self.auth_provider, 'auth_data'))

    def test_delete_auth_data_property_through_deleter(self):
        self.auth_provider.cache = 'foo'
        del self.auth_provider.auth_data
        self.assertIsNone(self.auth_provider.cache)

    def test_delete_auth_data_property_through_clear_auth(self):
        self.auth_provider.cache = 'foo'
        self.auth_provider.clear_auth()
        self.assertIsNone(self.auth_provider.cache)

    def test_set_and_reset_alt_auth_data(self):
        self.auth_provider.set_alt_auth_data('foo', 'bar')
        self.assertEqual(self.auth_provider.alt_part, 'foo')
        self.assertEqual(self.auth_provider.alt_auth_data, 'bar')

        self.auth_provider.reset_alt_auth_data()
        self.assertIsNone(self.auth_provider.alt_part)
        self.assertIsNone(self.auth_provider.alt_auth_data)


class TestKeystoneV2AuthProvider(BaseAuthTestsSetUp):
    _endpoints = fake_identity.IDENTITY_V2_RESPONSE['access']['serviceCatalog']
    _auth_provider_class = auth.KeystoneV2AuthProvider

    def setUp(self):
        super(TestKeystoneV2AuthProvider, self).setUp()
        self.stubs.Set(http.ClosingHttp, 'request',
                       fake_identity._fake_v2_response)
        self.target_url = 'test_api'

    def _get_fake_alt_identity(self):
        return fake_identity.ALT_IDENTITY_V2_RESPONSE['access']

    def _get_result_url_from_endpoint(self, ep, endpoint_type='publicURL',
                                      replacement=None):
        if replacement:
            return ep[endpoint_type].replace('v2', replacement)
        return ep[endpoint_type]

    def _get_token_from_fake_identity(self):
        return fake_identity.TOKEN

    def _test_request_helper(self, filters, expected):
        url, headers, body = self.auth_provider.auth_request('GET',
                                                             self.target_url,
                                                             filters=filters)

        self.assertEqual(expected['url'], url)
        self.assertEqual(expected['token'], headers['X-Auth-Token'])
        self.assertEqual(expected['body'], body)

    def test_request(self):
        filters = {
            'service': 'compute',
            'endpoint_type': 'publicURL',
            'region': 'FakeRegion'
        }

        url = self._get_result_url_from_endpoint(
            self._endpoints[0]['endpoints'][1]) + '/' + self.target_url

        expected = {
            'body': None,
            'url': url,
            'token': self._get_token_from_fake_identity(),
        }
        self._test_request_helper(filters, expected)

    def test_request_with_alt_auth_cleans_alt(self):
        self.auth_provider.set_alt_auth_data(
            'body',
            (fake_identity.ALT_TOKEN, self._get_fake_alt_identity()))
        self.test_request()
        # Assert alt auth data is clear after it
        self.assertIsNone(self.auth_provider.alt_part)
        self.assertIsNone(self.auth_provider.alt_auth_data)

    def test_request_with_alt_part_without_alt_data(self):
        """
        Assert that when alt_part is defined, the corresponding original
        request element is kept the same.
        """
        filters = {
            'service': 'compute',
            'endpoint_type': 'publicURL',
            'region': 'fakeRegion'
        }
        self.auth_provider.set_alt_auth_data('url', None)

        url, headers, body = self.auth_provider.auth_request('GET',
                                                             self.target_url,
                                                             filters=filters)

        self.assertEqual(url, self.target_url)
        self.assertEqual(self._get_token_from_fake_identity(),
                         headers['X-Auth-Token'])
        self.assertEqual(body, None)

    def test_request_with_bad_service(self):
        filters = {
            'service': 'BAD_SERVICE',
            'endpoint_type': 'publicURL',
            'region': 'fakeRegion'
        }
        self.assertRaises(exceptions.EndpointNotFound,
                          self.auth_provider.auth_request, 'GET',
                          self.target_url, filters=filters)

    def test_request_without_service(self):
        filters = {
            'service': None,
            'endpoint_type': 'publicURL',
            'region': 'fakeRegion'
        }
        self.assertRaises(exceptions.EndpointNotFound,
                          self.auth_provider.auth_request, 'GET',
                          self.target_url, filters=filters)

    def test_check_credentials_missing_attribute(self):
        for attr in ['username', 'password']:
            cred = copy.copy(self.credentials)
            del cred[attr]
            self.assertFalse(self.auth_provider.check_credentials(cred))

    def test_check_credentials_not_scoped_missing_tenant_name(self):
        cred = copy.copy(self.credentials)
        del cred['tenant_name']
        self.assertTrue(self.auth_provider.check_credentials(cred,
                                                             scoped=False))

    def test_check_credentials_missing_tenant_name(self):
        cred = copy.copy(self.credentials)
        del cred['tenant_name']
        self.assertFalse(self.auth_provider.check_credentials(cred))

    def _test_base_url_helper(self, expected_url, filters,
                              auth_data=None):

        url = self.auth_provider.base_url(filters, auth_data)
        self.assertEqual(url, expected_url)

    def test_base_url(self):
        self.filters = {
            'service': 'compute',
            'endpoint_type': 'publicURL',
            'region': 'FakeRegion'
        }
        expected = self._get_result_url_from_endpoint(
            self._endpoints[0]['endpoints'][1])
        self._test_base_url_helper(expected, self.filters)

    def test_base_url_to_get_admin_endpoint(self):
        self.filters = {
            'service': 'compute',
            'endpoint_type': 'adminURL',
            'region': 'FakeRegion'
        }
        expected = self._get_result_url_from_endpoint(
            self._endpoints[0]['endpoints'][1], endpoint_type='adminURL')
        self._test_base_url_helper(expected, self.filters)

    def test_base_url_unknown_region(self):
        """
        Assure that if the region is unknow the first endpoint is returned.
        """
        self.filters = {
            'service': 'compute',
            'endpoint_type': 'publicURL',
            'region': 'AintNoBodyKnowThisRegion'
        }
        expected = self._get_result_url_from_endpoint(
            self._endpoints[0]['endpoints'][0])
        self._test_base_url_helper(expected, self.filters)

    def test_base_url_with_non_existent_service(self):
        self.filters = {
            'service': 'BAD_SERVICE',
            'endpoint_type': 'publicURL',
            'region': 'FakeRegion'
        }
        self.assertRaises(exceptions.EndpointNotFound,
                          self._test_base_url_helper, None, self.filters)

    def test_base_url_without_service(self):
        self.filters = {
            'endpoint_type': 'publicURL',
            'region': 'FakeRegion'
        }
        self.assertRaises(exceptions.EndpointNotFound,
                          self._test_base_url_helper, None, self.filters)

    def test_base_url_with_api_version_filter(self):
        self.filters = {
            'service': 'compute',
            'endpoint_type': 'publicURL',
            'region': 'FakeRegion',
            'api_version': 'v12'
        }
        expected = self._get_result_url_from_endpoint(
            self._endpoints[0]['endpoints'][1], replacement='v12')
        self._test_base_url_helper(expected, self.filters)

    def test_base_url_with_skip_path_filter(self):
        self.filters = {
            'service': 'compute',
            'endpoint_type': 'publicURL',
            'region': 'FakeRegion',
            'skip_path': True
        }
        expected = 'http://fake_url/'
        self._test_base_url_helper(expected, self.filters)


class TestKeystoneV3AuthProvider(TestKeystoneV2AuthProvider):
    _endpoints = fake_identity.IDENTITY_V3_RESPONSE['token']['catalog']
    _auth_provider_class = auth.KeystoneV3AuthProvider
    credentials = {
        'username': 'fake_user',
        'password': 'fake_pwd',
        'tenant_name': 'fake_tenant',
        'domain_name': 'fake_domain_name',
    }

    def setUp(self):
        super(TestKeystoneV3AuthProvider, self).setUp()
        self.stubs.Set(http.ClosingHttp, 'request',
                       fake_identity._fake_v3_response)

    def _get_fake_alt_identity(self):
        return fake_identity.ALT_IDENTITY_V3['token']

    def _get_result_url_from_endpoint(self, ep, replacement=None):
        if replacement:
            return ep['url'].replace('v3', replacement)
        return ep['url']

    def test_check_credentials_missing_tenant_name(self):
        cred = copy.copy(self.credentials)
        del cred['domain_name']
        self.assertFalse(self.auth_provider.check_credentials(cred))

    # Overwrites v2 test
    def test_base_url_to_get_admin_endpoint(self):
        self.filters = {
            'service': 'compute',
            'endpoint_type': 'admin',
            'region': 'MiddleEarthRegion'
        }
        expected = self._get_result_url_from_endpoint(
            self._endpoints[0]['endpoints'][2])
        self._test_base_url_helper(expected, self.filters)
