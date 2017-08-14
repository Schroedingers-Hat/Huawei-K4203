import requests
import xml.etree.ElementTree as ET
import copy
import yaml
from collections import OrderedDict
import re
from io import BytesIO
from datetime import datetime

class HTTPStatus(Exception):
    pass

class APIError(Exception):
    pass

def get_token():
    '''
    Extract CORS token from vendor.js as the endpoints that work
    on other modems seem to be absent on the K4203.

    This seems to be the thing that changes most between models.
    Some do not require a token.
    '''
    vendor = requests.get("http://192.168.9.1/html/js/vendor.js")
    if vendor.status_code == 200:
        token = re.search('(?<=STR_AJAX_VALUE)\s*=\s\"(.*)\".*\n', vendor.text).group(1)
    else:
        raise HTTPStatus
    
    return token

def dict_to_xml(tag, d):
    '''
    Using ElementTree, convert a dictionary to its xml representation.
    '''
    elem = ET.Element(tag)
    for key, value in d.items():
        if type(value) == dict:
            child = dict_to_xml(key, value)
        else:
            child = ET.Element(key)
            child.text = str(value)
        elem.append(child)
    return elem
    
def tree_to_string(tree):
    pass
class APIRequest(object):
    def __init__(self, req_fun, url, **kwargs):
        self.req_fun = req_fun
        self.url = url
        self.kwargs = kwargs
    def run(self):
        return self.req_fun(self.url, **self.kwargs)

class HuaweiAPI(object):

    def __init__(self, filename):
        self.cfg_dict = yaml.load(open(filename,'r').read())
        self.common_headers = self.cfg_dict['common']['headers']
        self.error_codes = self.cfg_dict['common']['error-codes']
        self.base_url = 'http://' + self.common_headers['Host']
        self.api_dict = {k: v for k, v in self.cfg_dict.items() if not k == 'common-headers'}

    def list_requests(self):
        return [x for x in self.api_dict]

    def get_error(self, code):
        error_str = self.error_codes.get(code, "No such error code.")
        return error_str

    def make_request(self, name, **kwargs):
        '''
        Copy request from api and generate xml.
        '''
        if name not in self.api_dict:
            raise APIError
        cmd_dict = copy.deepcopy(self.api_dict.get(name))
        url = self.base_url + cmd_dict['url']
        xml_str = ''
        headers = copy.deepcopy(self.common_headers)
        method = cmd_dict['method']
        if method == 'post':
            # Modem responds with error if XML is reordered.
            request = OrderedDict(cmd_dict['request'])
            if cmd_dict.get('Referer'):
                headers['Referer'] = cmd_dict['Referer']
            request['token'] = get_token()
            # Todo: The xml can have multiple values with the same tag
            # such as phones. Dictionaries are not the best structure for this.
            for key, value in kwargs.items():
                if key in request:
                    if type(value) == dict:
                        request[key] = value
                    else:
                        request[key] = str(value)
            xml_str = ET.tostring(dict_to_xml('request', request))
            xml_str = b"<?xml version='1.0' encoding='UTF-8'?>" + xml_str
            return APIRequest(requests.post, url, headers=headers, data = xml_str)
        elif method == 'get':
            return APIRequest(requests.get, url)

    def run_command(self, name, **kwargs):
        req = self.make_request(name, **kwargs)
        response = req.run()
        return response.status_code, response_to_dict(response)
 
    def send_sms(self, content, number):
        '''Send sms to numbers
        Arguments:
        number --- string representing phone number, ie. '0412345678'
        content --- string containing message body.
        '''
        # For some reason the web interface adds one to content length.
        # also don't know how unicode effects this.
        length = len(content) + 1

        # Datetime in iso format
        date_str = datetime.now().replace(microsecond=0).isoformat()

        return self.run_command('sms', Content=content,
                                       Length=length,
                                       Date=date_str, 
                                       Phones={'Phone': number})


def response_to_dict(r):
    return etree_to_dict(ET.fromstring(r.text))

def etree_to_dict(t):
    return {t.tag : {x.tag: etree_to_dict(x) for x in t.getchildren()} or t.text}
api = HuaweiAPI('huawei-K4203-api.yml')

