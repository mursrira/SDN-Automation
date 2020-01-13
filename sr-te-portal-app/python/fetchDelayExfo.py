from ncs.application import Application
from helpers import Helpers
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
import threading
import ConfigParser
import time
import subprocess
from helpers import Helpers
from datetime import datetime
#import pysftp
from com.cisco.wae.opm.network.model.node.key import NodeKey
from com.cisco.wae.opm.network.model.interface.key import InterfaceKey
import csv,_ncs,ncs,requests,json

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------


class FetchDelay(Application):

	def setup(self):
		self.log.info('fetch-delay-exfo service starting..')
		self.register_action('fetch-delay-exfo-action-point',FetchDelayAction, [])
		self.log.info('fetch-delay-exfo service started')

	def teardown(self):

		self.log.info('fetch-delay-exfo service stopped')


class FetchDelayAction(OpmActionBase):

	config = ConfigParser.RawConfigParser()

	def run(self, net_name, input, output):

		self.update_start_status()
		self.log.info("Got request for Delay population to WAE network model")

		my_helper = Helpers(self.log)
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		# self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')

		#FETCH FROM Config File
		# Please Note Database and UOP are in same VM so using the same

		exfoVmIp = self.config.get('EXFOServer', 'SftpServer')
		sftpUserName = self.config.get('EXFOServer', 'SftpUserName')
		sftpPassword = self.config.get('EXFOServer', 'SftpUserPass')
		sftpFilePath = self.config.get('EXFOServer', 'SftpCsvFilePath')
		sftpLocalPath = self.config.get('EXFOServer', 'CsvFilePathLocal')

		#TODO
		#self.fetchFileFromServer(exfoVmIp,sftpUserName,sftpPassword,sftpLocalPath,sftpFilePath)

		start = time.time()
		##self.ifaceUtilizationThreshold   =   float(input.interface_utilization)
		#self.parseDelayCsvAndUpdateWMD()
		#self.parseDelayUpdatedCsvAndUpdateWMD()
		self.getDataFromEXFOServerAndUpdateWMD()

		# self.get_all_lsps_opm(net_name, output)
		#helpers =	 Helpers(self,input,output)

		currentTime = str(datetime.now())
		payload = "{\"last_collection_timestamp\": \""+currentTime+"\"}"

		#Update Delay collection TIME STAMP at UOP
		my_helper.invokeUOPRestApi('last_delay_time_stamp',"POST",payload)
		EndTime = time.time()
		self.log.info("Delay updation in WAE model took ", (EndTime - start), " seconds")



	'''def fetchFileFromServer(self,hostName,userName,passwd,localPath,remotePath):
		self.log.debug("Fetching file from Exfo Server: ", hostName)
		cnopts = pysftp.CnOpts()
		cnopts.hostkeys = None

		try:
			with pysftp.Connection(hostName,
								username=userName,
								password=passwd,
								cnopts = cnopts
								) as sftp:
				try:
					if(sftp.isfile(remotePath)):
						sftp.get(remotePath, localPath)
				except Exception as e1:
					self.log.error("File {} in remote EXFO server {} is not present and Error is {}".format(remotePath,hostName,e1))
			sftp.close()
		except Exception as e:
			self.log.error("Unable to Connect to EXFO Server hostname - {} and Error is {}".format(hostName,e))'''


	def parseDelayCsvAndUpdateWMD(self):

		#COMMENT LINE 119
		#self.fileName = "/opt/others/install-files/delay-updated-wmd.csv"
		sftpLocalPath = self.config.get('EXFOServer', 'CsvFilePathLocal')
		self.log.debug("Parsing Delay CSV file: ", sftpLocalPath)

		# PARSING CSV File and Filling cisrcuitsDelayDict Dictionary

		with open(sftpLocalPath,'r') as csvfile:
			csvreader = csv.reader(csvfile)
			fields = csvreader.next()
			try:
				#verifierIndex = fields.index('Verifier')
				#responderIndex = fields.index('Responder')
				srcIntfAdd = fields.index('Source Interface Address')
				destIntfAdd = fields.index('Destination Interface Address')
				avgNetRtDelay = fields.index('Average Network Round-Trip Delay')
				trafficSim = fields.index('Traffic Sim')
			except Exception as e:
				print(e)

			# circuitsDelayDict (Dictionary)
			# Key - InterfaceSourceIpAddress:::InterfaceDestinationIpAddress
			# Value - Delay Value for Above
			circuitsDelayDict = {}
			trafficDict = {}

			for row in csvreader:
				circuitDelayDictKey = str(row[srcIntfAdd])+':::'+str(row[destIntfAdd])
				circuitsDelayDict[circuitDelayDictKey] = row[avgNetRtDelay]
				trafficDict[circuitDelayDictKey] = row[trafficSim]

			self.log.info('SUCESSFULLY PARSED EXCEL and Made DELAY and TRAFFIC DICTIONARIES')
			self.log.debug("circuitsDelayDict: ",circuitsDelayDict)
			self.log.debug("trafficDict: ", trafficDict)

		my_helper = Helpers(self.log)

		network = my_helper.read_network()
		orig_network = my_helper.read_network()

		#self.planFile = '/opt/others/plan-files/etisalat-xtc-dare_delay_11.pln'
		#with open_plan(self.planFile) as self.network:

		circuits = network.model.circuits

		for circuit in circuits:
			#
			#Assumption - change - check - circuit.interface_a.ip_addresses[0]
			#
			try:
				circuitDelayDictKey = str(circuit.interface_a.ip_addresses[0])+':::'+str(circuit.interface_b.ip_addresses[0])
				circuitDelayDictKeyRev = str(circuit.interface_b.ip_addresses[0])+':::'+str(circuit.interface_a.ip_addresses[0])
			except (IndexError, ValueError):
				self.log.warning("Interfaces does not have ip-address, so ignoring them {}".format(circuit.name))
				continue
			#
			#DELAY
			#
			try:
				if circuitsDelayDict[circuitDelayDictKey] is not None:
					delayAToB = float(circuitsDelayDict[circuitDelayDictKey])
			except KeyError:
				delayAToB = None
			try:
				if circuitsDelayDict[circuitDelayDictKeyRev] is not None:
					delayBToA = float(circuitsDelayDict[circuitDelayDictKeyRev])
			except KeyError:
				delayBToA = None

			#delayBToA = float(circuitsDelayDict[circuitDelayDictKeyRev]) if circuitsDelayDict[circuitDelayDictKeyRev] else None
			if delayAToB is not None and delayBToA is not None:
				circuit.delay = (delayAToB+delayBToA)/2
				self.log.debug('DELAY AB,BA is {}-{}-{}'.format(delayAToB,delayBToA,circuit.delay))
				self.log.info('keys {}-{}'.format(circuitDelayDictKey,circuitDelayDictKeyRev))
			elif delayAToB is not None:
				circuit.delay = delayAToB
				#self.log.info('DELAY AB is {}-{}'.format(delayAToB,circuit.delay))
				#self.log.info('keys {}'.format(circuitDelayDictKey))
			elif delayBToA is not None:
				circuit.delay = delayBToA
				#self.log.info('DELAY BA is {}-{}'.format(delayBToA,circuit.delay))
				#self.log.info('keys {}'.format(circuitDelayDictKeyRev))
			else:
				self.log.debug("circuitDelayDictKey - {} is unavailable, So cannot fill delay in WMD !!!".format(circuitDelayDictKey))

			circuitDelay = circuit.delay

			#TODO
			#
			#FILLING TRAFFIC INFO
			#
			#self.log.info(float(trafficDict[circuitDelayDictKey]))
			#self.log.info(dir(circuit.interface_a))
			circuit.interface_a.measured_traffic = float(trafficDict[circuitDelayDictKey])
			self.log.debug('circuit.interface_a.measured_traffic {}'.format(circuit.interface_a.measured_traffic))
			#circuit.interface_a.simulated_traffic = float(trafficDict[circuitDelayDictKey])
			circuit.interface_b.measured_traffic = float(trafficDict[circuitDelayDictKeyRev])
			self.log.debug('circuit.interface_b.measured_traffic {}'.format(circuit.interface_b.measured_traffic))
			lsps = network.model.lsps

			'''for lsp in lsps:
				if "FJN-EMIX-RC_t12001" in lsp.name :
					lsp.measured_traffic = float(600)
				elif "lon-emix-ra_t12004" in lsp.name:
					lsp.measured_traffic = float(450)
				elif 'frk-emix-ra_t12012' in lsp.name:
					lsp.measured_traffic = float(450)
				elif "SKM-EMIX-RC_t12007" in lsp.name:
					lsp.measured_traffic = float(50)
				elif "frk-emix-ra_t12011" in lsp.name:
					lsp.measured_traffic = float(50)
				elif "frk-emix-ra_t12006" in lsp.name:
					lsp.measured_traffic = float(300)
				elif "frk-emix-ra_t12007" in lsp.name:
					lsp.measured_traffic = float(300)'''

			#TODO BLR VIRL LAB
			
			for lsp in lsps:
				if "36" in lsp.name or "37" in lsp.name :
					lsp.measured_traffic = float(400)
			

			self.log.info("Final circuit delay is {} for circuit".format(circuitDelay))

		patch_delay = network.model- orig_network.model
		if patch_delay:

			self.log.debug("patch-output",patch_delay)

			source_nw = self.config.get('WAEServer', 'Topo-BGPLS-XTC-NIMO-NetworkName')
			#TODO
			source_nw_cp = self.config.get('WAEServer', 'Traffic-NIMO-NetworkName')

			source_nw = self.config.get('WAEServer', 'Topo-BGPLS-XTC-NIMO-NetworkName')

			if self._send_patch(patch_delay, source_nw):
				self.log.debug('Applying Delay patch to DARE agg complete')

			if self._send_patch(patch_delay, source_nw_cp):
				self.log.debug('Applying Traffic patch to DARE agg complete')

		else:
			self.log.info('No change in Delay model, no patch to send')

	def parseDelayUpdatedCsvAndUpdateWMD(self):

		sftpLocalPath = self.config.get('EXFOServer', 'CsvFilePathLocal')
		self.log.debug("Parsing Delay CSV file: ", sftpLocalPath)

		# Parsing the CSV file and creating circuitsDelayDict
		with open(sftpLocalPath, 'r') as csvfile:
			csvreader = csv.reader(csvfile)
			fields = csvreader.next()
			try:
				srcIntfAdd = fields.index('verifier_id')
				destIntfAdd = fields.index('HOST_ID')
				avgNetRtDelay = fields.index('rt_latency_avg')
			except Exception as e:
				self.log.error(e)

			circuitsDelayDict = {}

			for row in csvreader:
				srcNode = (row[srcIntfAdd]).split('-')
				dstNode = (row[destIntfAdd])
				# Fetching destination node by comparing SiteIPMappings's key from properties file
				for key, value in self.config.items('SiteIPMappings'):
					if key in dstNode:
						dstNode = value.split('-')
				circuitDelayDictKey = str(srcNode[0]) + ':::' + str(dstNode[0])
				# if key has multiple delay values then appending duplicate values in list
				if circuitDelayDictKey in circuitsDelayDict.keys():
					circuitsDelayDict[circuitDelayDictKey].append(row[avgNetRtDelay])
				else:
					circuitsDelayDict[circuitDelayDictKey] = [row[avgNetRtDelay]]

		self.log.debug("circuitsDelayDict:", circuitsDelayDict)

		my_helper = Helpers(self.log)
		network = my_helper.read_network()		
		orig_network = my_helper.read_network() 

		#self.planFile = '/opt/others/plan-files/emix-cp.pln'
		#self.planOut = '/opt/others/plan-files/emix-cp_out.pln'

		circuits = network.model.circuits

		for circuit in circuits:
			# DELAY#
			#HANDLE ASN Nodes
			try:
				node_a = str(circuit.interface_a.node.name).split('-')
				node_b = str(circuit.interface_b.node.name).split('-')
				circuitDelayDictKey = node_a[0] + ':::' + node_b[0]
				circuitDelayReverseDictKey=node_b[0]+':::'+node_a[0]

			except Exception as e:
				self.log.error("Interface does not  have node  {}".format(e))
				continue
			try:
				# Finding average value of duplicate nodes and set to delayAtoB
				if circuitsDelayDict[circuitDelayDictKey] is not None:
					if circuitDelayReverseDictKey in circuitsDelayDict.keys():
						mergedList=circuitsDelayDict[circuitDelayDictKey]+circuitsDelayDict[circuitDelayReverseDictKey]
						convertedDelayValuesList= list(map(float, mergedList))
						avgDelayValue =(sum(convertedDelayValuesList) / len(convertedDelayValuesList))
					else:
						convertedDelayValuesList = list(map(float, circuitsDelayDict[circuitDelayDictKey]))
						avgDelayValue =(sum(convertedDelayValuesList) / len(convertedDelayValuesList))

			except KeyError:
				avgDelayValue = None

			# delayBToA = float(circuitsDelayDict[circuitDelayDictKeyRev]) if circuitsDelayDict[circuitDelayDictKeyRev] else None
			if avgDelayValue is not None:
				circuit.delay = avgDelayValue
			else:
				self.log.warning("circuitDelayDictKey - {} is unavailable, So cannot fill delay in WMD !!!".format(
					circuitDelayDictKey))

			
		patch_delay = network.model- orig_network.model

		if patch_delay:
			self.log.debug("delay-patch-output",patch_delay)
			source_nw = self.config.get('WAEServer', 'Topo-BGPLS-XTC-NIMO-NetworkName')

			if self._send_patch(patch_delay, source_nw):
				self.log.debug('Applying Delay patch to DARE agg complete')

		else:
			self.log.info('No change in Delay model, no patch to send')
	
	def getDataFromEXFOServerAndUpdateWMD(self):
		my_helper = Helpers(self.log)
		testHandleIdDictWithKey={} 
		finalDictWithAvgDelayAndKey={}
		onDemandTwampLoginHeadersPayload,onDemandTwampLoginBodyPayload=my_helper.generatePayloadForExfo(requestType="GET_LOGIN")
		self.log.debug("Returned headersPayload{} and bodyPayload{} for EXFO TWAMP Login API ".format(onDemandTwampLoginHeadersPayload,onDemandTwampLoginBodyPayload))
		try:
			loginResponse=my_helper.invokeEXFOServerRestApi(url="Login",requestType="POST_LOGIN",onDemandTwampHeadersPayload=onDemandTwampLoginHeadersPayload,onDemandTwampBodyPayload=onDemandTwampLoginBodyPayload)
			self.log.debug("EXFO Login API response ",loginResponse)
			keysList=list(loginResponse.keys())
			brixAuthToken=keysList[0]+"="+loginResponse['BRIX_AUTH_TOKEN']
		except(Exception) as e:
			self.log.debug("Exception at Login API ",e)
			
		onDemandTwampRunHeadersPayload,onDemandTwampRunfinalBodyPayloadDict=my_helper.generatePayloadForExfo(requestType="POST_RUN",brixAuthToken=brixAuthToken)
		self.log.debug("Returned headersPayload{} and bodyPayload{} for EXFO TWAMP Run API ".format(onDemandTwampRunHeadersPayload,onDemandTwampRunfinalBodyPayloadDict))
		for key,value in onDemandTwampRunfinalBodyPayloadDict.items():
			try:
				runResponse=my_helper.invokeEXFOServerRestApi(url="OnDemand/v1/Run", requestType="POST_RUN",onDemandTwampBodyPayload=onDemandTwampRunfinalBodyPayloadDict[key],onDemandTwampHeadersPayload=onDemandTwampRunHeadersPayload)
				testHandleIdDict=json.loads(runResponse)
				testHandleId=testHandleIdDict['result']['test_handle']
				self.log.debug("TestHandleId ",testHandleId)
				testHandleIdDictWithKey[key]=testHandleId
			except(Exception) as e:
				self.log.debug("Exception at run API ",e)
				pass
		self.log.debug("Test HandleId Dict with key ",testHandleIdDictWithKey)

		onDemandTwampResultHeadersPayload=my_helper.generatePayloadForExfo(requestType="GET_RESULT",brixAuthToken=brixAuthToken)
		time.sleep(10)
		
		for key,value in testHandleIdDictWithKey.items():
			try:
				url="OnDemand/v1/Run/"+value
				getResultResponse=my_helper.invokeEXFOServerRestApi(url=url,requestType="GET_RESULT",onDemandTwampBodyPayload="",onDemandTwampHeadersPayload=onDemandTwampResultHeadersPayload,brixAuthToken=brixAuthToken)
				convertGetResultResponseToDict=json.loads(getResultResponse)
				self.log.debug("Get result API response ",convertGetResultResponseToDict)
				finalDictWithAvgDelayAndKey[key]=convertGetResultResponseToDict['result']['test_run_info']['results']['fixed_results']['rt_latency_avg']
				
			except(Exception) as e:
				self.log.debug("Exception at get Result API ",e)
				pass
		self.log.debug("Final dict to update WAE Model ",finalDictWithAvgDelayAndKey)

		onDemandTwampLogoffHeadersPayload=my_helper.generatePayloadForExfo(requestType="GET_LOGOFF",brixAuthToken=brixAuthToken)
		getLogOffResponse=my_helper.invokeEXFOServerRestApi(url="Logoff/HTTP/1.1",requestType="GET_LOGOFF",onDemandTwampBodyPayload="",onDemandTwampHeadersPayload=onDemandTwampLogoffHeadersPayload,brixAuthToken=brixAuthToken)
		self.log.debug("EXFO Logoff API response ",getLogOffResponse)
		circuitsDelayDict=finalDictWithAvgDelayAndKey
		self.log.debug("circuitsDelayDict:", circuitsDelayDict)

		
		network = my_helper.read_network()		
		orig_network = my_helper.read_network() 

		#self.planFile = '/opt/others/plan-files/emix-cp.pln'
		#self.planOut = '/opt/others/plan-files/emix-cp_out.pln'

		circuits = network.model.circuits

		for circuit in circuits:
			# DELAY#
			#HANDLE ASN Nodes
			try:
				node_a = str(circuit.interface_a.node.name).split('-')
				node_b = str(circuit.interface_b.node.name).split('-')
				circuitDelayDictKey = node_a[0] + ':::' + node_b[0]
				circuitDelayReverseDictKey=node_b[0]+':::'+node_a[0]

			except Exception as e:
				self.log.error("Interface does not  have node  {}".format(e))
				continue

			try:
				if circuitsDelayDict[circuitDelayDictKey] is not None:
					delayAToB = float(circuitsDelayDict[circuitDelayDictKey])
			except KeyError:
				delayAToB = None
			try:
				if circuitsDelayDict[circuitDelayReverseDictKey] is not None:
					delayBToA = float(circuitsDelayDict[circuitDelayReverseDictKey])
			except KeyError:
				delayBToA = None

			if delayAToB is not None:
				circuit.delay = delayAToB
				self.log.info('DELAY AB is {}-{}'.format(delayAToB,circuit.delay))
				self.log.info('keys {}'.format(circuitDelayDictKey))
			elif delayBToA is not None:
				circuit.delay = delayBToA
				self.log.info('DELAY BA is {}-{}'.format(delayBToA,circuit.delay))
				self.log.info('keys {}'.format(circuitDelayReverseDictKey))
			else:
				self.log.debug("circuitDelayDictKey - {} is unavailable, So cannot fill delay in WMD !!!".format(circuitDelayDictKey))

			
		patch_delay = network.model- orig_network.model

		if patch_delay:
			self.log.debug("delay-patch-output",patch_delay)
			source_nw = self.config.get('WAEServer', 'Topo-BGPLS-XTC-NIMO-NetworkName')
			source_nw = self.config.get('WAEServer', 'Topo-BGPLS-XTC-NIMO-NetworkName')

			if self._send_patch(patch_delay, source_nw):
				self.log.debug('Applying Delay patch to DARE agg complete')

		else:
			self.log.info('No change in Delay model, no patch to send')

	


	def _send_patch(self, patch, source_nw):
		patchstart = time.time()
		self.log.info('Sending patch to DARE')
		username = self.config.get('WAEServer', 'OPMRestAPIUserName')
		password = self.config.get('WAEServer', 'OPMRestAPIUserPass')

		with ncs.maapi.single_read_trans(username, password) as transaction:
				root = ncs.maagic.get_root(transaction)
				dare = root.wae.components.aggregators
				options = dare.send_patch.get_input()
				options.network = source_nw
				options.patch = patch
				output = dare.send_patch(options)
				if output.status: # True for success, False for error
					patchEnd = time.time()
					self.log.info("Sending Patch to DARE took ", patchEnd - patchstart, " seconds")
					return True
				self.log.error('Error while sending patch: ' + output.message)
		return False
