import json
import requests
from requests.auth import HTTPBasicAuth
import ConfigParser
from tePortalLauncher import TePortalLauncher

class LspDetailsCache:
	__instance = None
	log = None
	config = ConfigParser.RawConfigParser()

	# {"lspSrcNode:::lspName", "fwdClass:sla"}
	lspDetails = {}

	@staticmethod
	def getInstance(log):
		""" Static access method. """
		if LspDetailsCache.__instance == None:
			LspDetailsCache(log)
		return LspDetailsCache.__instance

	def __init__(self, log):
		""" Virtually private constructor. """
		if LspDetailsCache.__instance != None:
			raise Exception("This class is a LspDetailsCache!")
		else:
			LspDetailsCache.__instance = self
			self.log = log
			self.headers = {
				'content-type': "application/vnd.yang.operation+json"
			}


	def refreshLSPDetailsFromUOP(self):
		#response = self.my_helper.invokeUOPRestApi('details', 'GET', None)
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.lspDetails = {}
		uopVmIp = self.config.get('UOPServer', 'ServerRestURL')
		restApiUserName = self.config.get('UOPServer', 'RestAPIUserName')
		restApiPassword = self.config.get('UOPServer', 'RestAPIUserPass')
		url = uopVmIp+"/api/lsp/optimization/details"
		self.log.info("Pulling LSP details from UOP {}".format(url))
		try:
			response = requests.request("GET", url, auth=HTTPBasicAuth(restApiUserName,restApiPassword),headers=self.headers,verify=False)
			res_json=json.loads(response.text)
			if res_json['meta']['success']:
				lsps = res_json['data']['data']
				for lsp in lsps:
					if lsp['sla'] is None:
						sla = 'N/A'
					else:
						sla = lsp['sla']
					key = lsp['node_name']+':::'+lsp['lsp_name']
					val = str(lsp['class_of_service']) + ',' + str(sla)
					self.lspDetails[key] = val
					self.log.debug("LSP details fetched from UOP {}->{}".format(key, val))
			self.log.info("Refreshed {} LSP details from UOP {}".format(len(self.lspDetails), url))
		except(Exception) as err:
			self.log.error("Requested method is not present for API {}".format(url))
			raise Exception(err)

	def getLSPsOfClass(self, fwdClass):
		matching_lsps = []
		for key, value in self.lspDetails.iteritems():
			class_sla = value.split(',')
			fwd_class = class_sla[0]
			if(fwd_class in fwdClass):
				matching_lsps.append(key)
		return matching_lsps

	def getLSPDelaySLA(self, lspSrcNode, lspName):
		try:
			class_sla =  self.lspDetails[lspSrcNode+':::'+lspName]
			sla = class_sla.split(',')[1]
		except KeyError as e:
			self.log.error("SLA info not found from UOP - Tunnel is present in WAE not present NSO for "+ lspSrcNode+':::'+lspName + ", so returning -1.0 : ", e)
			#TODO
			#sla = float(-1.0)
			sla = 'N/A'
			#sla = float(100.0)
		return sla

	def getLSPClass(self, lspSrcNode, lspName):
		try:
			class_sla =  self.lspDetails[lspSrcNode+':::'+lspName]
			fwd_class = class_sla.split(',')[0]
		except KeyError as e:
			self.log.error("Fwd Calss info not found from UOP for "+ lspSrcNode+':::'+lspName + ", so returning 0 : ", e)
			fwd_class = 'None'
		return fwd_class
