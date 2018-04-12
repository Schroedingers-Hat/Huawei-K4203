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


class APIRequest(object):
    def __init__(self, req_fun, url, **kwargs):
        self.req_fun = req_fun
        self.url = url
        self.kwargs = kwargs
    def run(self):
        return self.req_fun(self.url, **self.kwargs)

class HuaweiAPI(object):

    def __init__(self, filename = 'huawei-K4203-api.yml'):
        self.cfg_dict = yaml.load(open(filename,'r').read())
        self.common_headers = self.cfg_dict['common']['headers']
        self.error_codes = self.cfg_dict['common']['error-codes']
        self.base_url = 'http://' + self.common_headers['Host']
        self.api_dict = {k: v for k, v in self.cfg_dict.items() if not k == 'common-headers'}


    def get_token(self):
        '''
        Extract CORS token from vendor.js as the endpoints that work
        on other modems seem to be absent on the K4203.

        This seems to be the thing that changes most between models.
        Some do not require a token.
        '''
        vendor = requests.get(self.base_url + "/html/js/vendor.js")
        if vendor.status_code == 200:
            token = re.search('(?<=STR_AJAX_VALUE)\s*=\s\"(.*)\".*\n', vendor.text).group(1)
        else:
            raise HTTPStatus
        
        return token

    def list_requests(self):
        return [x for x in self.api_dict]

    def get_error(self, code):
        '''
        Return string for Huawei's custom error code.
        Note that the values packaged in k4203.yml are not comprehensive.
        '''
        error_str = self.error_codes.get(code, "No such error code.")
        return error_str

    def make_request(self, name, **kwargs):
        '''
        Copy request from api and generate xml.
        Fields are defaulted to what is found in the loaded yml file.
        They can be overridden with kwargs.
        Example:
        >>>self.run_command('sms', Content="Example",
                       Length=7,
                       Date='2017-08-24T01:05:11', 
                       Phones={'Phone': '0412345678})

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
            request['token'] = self.get_token()
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
        '''
        Send command from API with arguments defaulting to those
        provided in yml.
        Anything provided in kwargs will override defaults.
        '''
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

    def get_inbox(self):
        '''
        Returns list of dictionaries containing SMS messages
        stored on modem/SIM.
        example:
        >>> api.get_inbox()
        [{'SaveType': '4', 'Priority': '0', 'Smstat': '0', 'Date': '2017-08-22 16:39:25', 'Index': '40007', 'Phone': '+61123456789', 'Content': 'Test', 'SmsType': '1', 'Sca': None}]
        '''
        response = self.run_command('sms-list')
        if response[0] == 200:
            message_dict = response[1]['response'].get('Messages')
            if type(message_dict) == dict:
                messages = message_dict.get('Message')
                # If we have a single message it doesn't come in a list
                if type(messages) != list:
                    messages = [messages]
                return messages
            else:
                return []
        else:
            raise HTTPStatus

    def clear_inbox(self):
        '''
        Iterate over messages in inbox and delete them.
        '''
        inbox = self.get_inbox()
        responses = []
        for message in inbox:
            idx = message.get('Index')
            response = self.run_command('sms-delete', Index=idx)
            responses.append(response)
        return responses
        

def response_to_dict(r):
    return etree_to_dict(ET.fromstring(r.text))

def etree_to_dict(element_tree):
    """Traverse the given XML element tree to convert it into a dictionary.
 
    :param element_tree: An XML element tree
    :type element_tree: xml.etree.ElementTree
    :rtype: dict

    Credit Eric Scrivener
    """
    def internal_iter(tree, accum):
        """Recursively iterate through the elements of the tree accumulating
        a dictionary result.
 
        :param tree: The XML element tree
        :type tree: xml.etree.ElementTree
        :param accum: Dictionary into which data is accumulated
        :type accum: dict
        :rtype: dict
        """
        if tree is None:
            return accum
 
        if tree.getchildren():
            accum[tree.tag] = {}
            for each in tree.getchildren():
                result = internal_iter(each, {})
                if each.tag in accum[tree.tag]:
                    if not isinstance(accum[tree.tag][each.tag], list):
                        accum[tree.tag][each.tag] = [
                            accum[tree.tag][each.tag]
                        ]
                    accum[tree.tag][each.tag].append(result[each.tag])
                else:
                    accum[tree.tag].update(result)
        else:
            accum[tree.tag] = tree.text
 
        return accum
 
    return internal_iter(element_tree, {})


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

if __name__ == "__main__":
    api = HuaweiAPI()
    print(*api.list_requests())
