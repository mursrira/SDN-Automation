from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
from contextlib import contextmanager
import com.cisco.wae.design
import threading
import ConfigParser
import time
import subprocess
import srTeBwOptimizer
import srTeDelayOptimizer
from com.cisco.wae.design import ServiceConnectionManager
from helpers import Helpers
import logging
import ncs
import json
import requests
from requests.auth import HTTPBasicAuth
from ncs.dp import Action

class LspFwdClassUpdater(Application):
	def setup(self):
		self.log.info('fetching class info from lsp........')
		self.register_action('lspFwdClassUpdater-action-point',classInfo, [])
	
	def teardown(self):
		self.log.info('fetch class action stopped')

class classInfo(OpmActionBase):

	config = ConfigParser.RawConfigParser()
	# Reading configuration file for config params at runtime

	def invokeNsoActionFetchClass(self,input):

		try:
			self.config.read(TePortalLauncher.portal_config_file)
			my_helper = Helpers(self.log)
			nsoVmIp = self.config.get('NSOServer', 'ServerRestURL')
			restApiUserName = self.config.get('NSOServer', 'RestAPIUserName')
			restApiPassword = self.config.get('NSOServer', 'RestAPIUserPass')

			url = nsoVmIp+"/api/running/fetch/fetchLspFwdClass/_operations/"

			header = {
				'content-type': "application/vnd.yang.data+json",
				'Authorization':"Basic YWRtaW46YWRtaW4="
				}

			payload = "{\"input\":{\"forwardClass\":\""+str(input.forwardClass)+"\"}}"

			response = requests.request("POST", url ,auth=HTTPBasicAuth(restApiUserName,restApiPassword),headers=header, data=payload, verify=False)
			self.log.info("Rest response from OPM :"+response.content)
			if(response.content):
				res_json = json.loads(response.content, strict=False)
				self.log.debug(res_json['fetchLspFwdClass:output'])
				uopPayload = ""
				uopPayload = uopPayload + "["
				self.log.info(res_json['fetchLspFwdClass:output']['lspClasses'])
				for lsp in res_json['fetchLspFwdClass:output']['lspClasses']:
					tunnel_name = str(lsp['deviceName']) + "_t" + str(lsp['te_name'])
					uopPayload = uopPayload + "{ \"node_name\": \""+lsp['deviceName']+"\",\"lsp_name\":\""+tunnel_name+"\",\"class_of_service\":\""+lsp['forwardClass']+"\"},"		
				uopPayload = uopPayload[:-1] + "]"
				self.log.debug("Payload generated to be pushed to UOP:",uopPayload)

				response = my_helper.invokeUOPRestApi('details/', "POST", uopPayload)
				self.log.info("Rest response from UOP :{}".format(response))


		except (KeyError, IndexError, ValueError, NameError, ) as err:
			self.log.error(err)
			raise err
		except Exception as e:
			self.log.error(e)
			raise Exception("Failed due to internal error. Details are logged.",e)



	def run(self, net_name, input, output):
		self.log.info('Fetching LSP class info from NSO')
		self.invokeNsoActionFetchClass(input)
