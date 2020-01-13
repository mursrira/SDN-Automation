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
from lspDetailsCache import LspDetailsCache
from com.cisco.wae.design import ServiceConnectionManager
from helpers import Helpers
import logging
import ncs
from ncs.dp import Action
import requests
import json
from requests.auth import HTTPBasicAuth
import json

class CloseLoopAutomation(Application):
	def setup(self):
		self.log.info('close Loop service starting')
		self.register_action('closeLoop-action-point',CloseLoop, [])

	def teardown(self):
		self.log.info('close Loop service stopped')

class CloseLoop(OpmActionBase):

	config = ConfigParser.RawConfigParser()
	config.read(TePortalLauncher.portal_config_file)
	

	def getFetchCongestion(self,my_helper):
		self.log.debug("Invoking callFetchCongestion()")
		try:
			resp_json = my_helper.invokeUOPRestApi('get_lsp_threshold', "GET", None)
			threshold = str(resp_json['data'][0]['lsp_congestion_threshold'])
			self.log.info("CloseLoop is invoked at.{}".format(threshold))
			response = my_helper.callFetchCongestion(threshold)
			self.log.debug("Close Loop Fetch Congestion Response :",response)
			fetch_congestion_res = response
			return fetch_congestion_res,threshold
		except(Exception) as err:
			self.log.debug(err)
			pass
			

	def callHybridOptimizer(self, fetch_congestion_res,threshold,my_helper):
		try:
			self.log.debug("Preparing congested_lsps_list")
			self.log.debug("Invoking invokeUOPRestApi() to fetch threshold_cross_count value")
			company_config_response=my_helper.invokeUOPRestApi('company_config', "GET", " ")
			congReportCount = int(company_config_response['data'][0]['threshold_cross_count'])			
			#congReportCount = int(self.config.get('WAECongestionDetection','congestionRecurrCountb4Reporting'))
			delay_congestions, bandwidth_congestions = self.loadCongestedTunnels()
			congested_lsps_list=[]
			congested_lsps_to_be_reported = []
			congested_lsps_to_be_ignored=[]
			congested_lsps_list_payload=[]
			for congested_lsp in fetch_congestion_res['sr-fetch-congestion:output']['congested-lsps']:
				if(congested_lsp['lspClass'] != str(1)):
					lspKeyStr=congested_lsp['lspName']+':::'+congested_lsp['lspSrcNode']
					congested_lsps_list.append(lspKeyStr)
					if (bandwidth_congestions.has_key(lspKeyStr) and int(bandwidth_congestions[lspKeyStr]) >= congReportCount):
						congested_lsps_to_be_reported.append(lspKeyStr)
					else:
						congested_lsps_to_be_ignored.append(lspKeyStr)
			self.log.info("Congested LSPs list that didn't cross threshold count",congested_lsps_to_be_ignored)
			self.log.info("Invoking updateViolationLspDict() to update congested LSPs in DelayCongestedTunnels file")
			self.updateViolationLspDict(bandwidth_congestions, congested_lsps_list)
			congested_lsps_list_payload=my_helper.generateOpmPayload(payload_type="bandwidth",congested_lsps_to_be_reported=congested_lsps_to_be_reported)
			self.log.debug("Genrerated Congested LSPs payload to invoke hybdrid optimizer",congested_lsps_list_payload)  
		except(Exception) as err:
			congested_lsps_list_payload=my_helper.generateOpmPayload(payload_type="bandwidth",congested_lsps_to_be_reported=congested_lsps_to_be_reported)
			self.log.debug(err)
			pass		

		try:
			self.log.debug("Preparing sla_violated_lsps")
			sla_violated_lsps = []
			sla_violated_lsps_to_be_reported = []
			sla_violated_lsps_to_be_ignored=[]
			sla_violated_lsps_list_payload=[]
			
			for sla_violated_lsp in fetch_congestion_res['sr-fetch-congestion:output']['sla-violated-lsps']:
				if (sla_violated_lsp['lspClass'] == str(1)):
					lspKeyStr=sla_violated_lsp['lspName']+':::'+sla_violated_lsp['lspSrcNode']
					sla_violated_lsps.append(lspKeyStr)
					if (delay_congestions.has_key(lspKeyStr) and int(delay_congestions[lspKeyStr]) >= congReportCount):
						sla_violated_lsps_to_be_reported.append(lspKeyStr)
					else:
						sla_violated_lsps_to_be_ignored.append(lspKeyStr)
			self.log.info("SLA violated LSPs list that didn't cross threshold count",sla_violated_lsps_to_be_ignored)
			self.log.info("Invoking updateViolationLspDict() to update SLA violated LSPs in DelayCongestedTunnels file")		
			self.updateViolationLspDict(delay_congestions, sla_violated_lsps)
			sla_violated_lsps_list_payload=my_helper.generateOpmPayload(payload_type="delay",sla_violated_lsps_to_be_reported=sla_violated_lsps_to_be_reported)
			self.log.debug("Genrerated sla_violated LSPs payload to invoke hybdrid optimizer",sla_violated_lsps_list_payload) 
		except(Exception)as err:
			sla_violated_lsps_list_payload=my_helper.generateOpmPayload(payload_type="delay",sla_violated_lsps_to_be_reported=sla_violated_lsps_to_be_reported)
			self.log.debug(err)
			pass

		self.log.debug("Invoking saveCongestedTunnels() to save congested and sla violated LSPs in DelayCongestedTunnels file")   
		self.saveCongestedTunnels(bandwidth_congestions,delay_congestions)
				
		try:
			# Invoke Hybrid Optimizer
			hybdrid_optimizer_res=None
			err=None
			if(self.should_Optimizer_be_invoked(congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported,my_helper)):
				self.log.debug("CloseLoop is invoking hybdrid optimizer")
				#payload = "{ \"input\": { \"post-optimization-threshold\":" + threshold + ", \"action-type\": \"force-commit\",\"lsps-to-be-optimized\":" + congested_lsps_list_payload + ",\"exclude-vip-tunnels\": \"true\",\"create-new-lsps\": true,\"delay-lsps-to-be-optimized\":" + sla_violated_lsps_list_payload + "}}"
				if(self.should_create_lsps_send_in_email_notificaiton(my_helper)):
					payload = my_helper.generateOpmPayload(payload_type="hybrid_optimizer_payload",threshold=threshold ,congested_lsps_list_payload=congested_lsps_list_payload, sla_violated_lsps_list_payload=sla_violated_lsps_list_payload,create_lsp=True)
				else:
					payload = my_helper.generateOpmPayload(payload_type="hybrid_optimizer_payload",threshold=threshold ,congested_lsps_list_payload=congested_lsps_list_payload, sla_violated_lsps_list_payload=sla_violated_lsps_list_payload,create_lsp=False)
				self.log.debug("Payload Generated to invoke hybrid optimizer: ", payload)
				response = my_helper.invokeWaeOpmRestApi("opm/hybrid-optimizer/doBothDelayBandwidth", "POST", payload)
				self.log.debug("Hybrid Optimizer response :", response)
				hybdrid_optimizer_res = response				
				self.log.debug("Invoking removeViolationDictKey() to remove sla violated and congested LSPs from DelayCongestedTunnels File ")
				self.removeViolationDictKey(congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported)

			self.invokeEmailNotification(my_helper,fetch_congestion_res,congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported,hybdrid_optimizer_res,congested_lsps_to_be_ignored,sla_violated_lsps_to_be_ignored,err)
			self.log.debug("CloseLoop End...")
		except(Exception) as err:
			#STANDARAD NSO ERROR
			self.invokeEmailNotification(my_helper,fetch_congestion_res,congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported,hybdrid_optimizer_res,congested_lsps_to_be_ignored,sla_violated_lsps_to_be_ignored,err)
			raise Exception("Not succesful in running LSP-Closed-Loop ",str(err))
	
	def	invokeEmailNotification(self,my_helper,fetch_congestion_res,congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported,hybdrid_optimizer_res,congested_lsps_to_be_ignored,sla_violated_lsps_to_be_ignored,err):
		#Altering fetch congestion response
		self.log.debug("Invoking updateFetchCongestionResWithReportedLsp() to alter LSPs in fetchcongestion response ")
		fetch_congestion_res=self.updateFetchCongestionResWithReportedLsp(fetch_congestion_res,congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported)				
		if(fetch_congestion_res is None and hybdrid_optimizer_res is None):
			self.log.debug("No LSPs for re-route")
		else:
			hybdrid_optimizer_res=self.removeIgnoredLspsFromHybridOptimizerRes(hybdrid_optimizer_res,congested_lsps_to_be_ignored,sla_violated_lsps_to_be_ignored)
			self.log.debug("Sending email notification")
			self.log.debug("Hybrid optimizer content for email ",hybdrid_optimizer_res)
			self.log.debug("Fetch congestion content for email ",fetch_congestion_res)
			self.log.debug("Error@invokeEmailNotfication ",err)
			my_helper.sendEmailNotification(fetch_congestion_res, hybdrid_optimizer_res,err)
		
	def should_create_lsps_send_in_email_notificaiton(self,my_helper):
		self.log.debug("this block checks if is_lsp_create_lsps flag is true then send create and deleted lsps otherwise no")
		company_config_response = my_helper.invokeUOPRestApi('company_config', "GET", " ")
		self.log.info("is_lsp_create_lsps flag is ",company_config_response['data'][0]['is_lsp_create_lsps'])
		return company_config_response['data'][0]['is_lsp_create_lsps']


	def should_Optimizer_be_invoked(self,congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported,my_helper):
		self.log.debug("invoking company_config UOP API")
		self.log.debug("Size of congested_lsps_to_be_reported list ",congested_lsps_to_be_reported)
		self.log.debug("Size of sla_violated_lsps_to_be_reported_list",sla_violated_lsps_to_be_reported)
		company_config_response = my_helper.invokeUOPRestApi('company_config', "GET", " ")
		self.log.info("is_lsp_opt_closed_loop flag is ",company_config_response['data'][0]['is_lsp_opt_closed_loop'])
		#add below flag at the place of True,
		return ((len(sla_violated_lsps_to_be_reported)>0 or len(congested_lsps_to_be_reported)>0) and (company_config_response['data'][0]['is_lsp_opt_closed_loop']))
	
	def updateViolationLspDict(self, violation_dict, violated_lsps,):
		self.log.debug("updated dictonary post fetch congestion:{}".format(violated_lsps))
		# Add new congestions and repeat recurring ones
		for l in violated_lsps:
			if(violation_dict.has_key(l)):
				violation_dict[l] = violation_dict[l]+1
			else:
				violation_dict[l] = 1
		self.log.debug("With New LSPs ", violation_dict)

	def removeViolationDictKey(self,congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported):
		# Remove Congestions that didnt repeat this time from last time
		self.log.debug("Reading DelayCongestedTunnels")
		delay_congestions, bandwidth_congestions = self.loadCongestedTunnels()
		self.log.info("SLA violated LSPs dict loaded from DelayCongestedTunnels file",delay_congestions)
		self.log.info("Congested LSPs dict loaded from DelayCongestedTunnels file ",bandwidth_congestions)
		merged_congested_sla_violated_lsps_list=sla_violated_lsps_to_be_reported+congested_lsps_to_be_reported
		self.log.debug("Merged congested and sla violated LSPs list ",merged_congested_sla_violated_lsps_list)
		try:
			for congestedkey in merged_congested_sla_violated_lsps_list:
				if(congestedkey in delay_congestions):
					del delay_congestions[congestedkey]
				if(congestedkey in bandwidth_congestions):
					del bandwidth_congestions[congestedkey]
		except(Exception) as err:
			self.log.error(err)
			pass
				
		self.log.debug("SLA violated LSPs Dict With New LSPs and without prev LSPs after removing keys ", delay_congestions)
		self.log.debug("Congested LSPs Dict With New LSPs and without prev LSPs after removing keys, ", bandwidth_congestions)
		self.log.info("Invoking saveCongestedTunnels() to save congested and sla violated LSPs in DelayCongestedTunnels file")
		self.saveCongestedTunnels(bandwidth_congestions,delay_congestions)
		

	def loadCongestedTunnels(self):
		try:
			bandwidth_congestions = {}
			delay_congestions = {}
			#congestionCount = self.config.get('WAEPortal','congestionRecurrCountb4Reporting')
			#resp_json = self.my_helper.invokeUOPRestApi('get_threshold_cross_count', "GET", None)
			#congestionCount = str(resp_json['data'][0]['threshold_cross_count'])
			congestionFile = self.config.get('WAECongestionDetection','congestedTunnelsFile')
			
			with open(congestionFile) as ifCmdFile:
				content = ifCmdFile.readlines()
				count = 1
				for line in content:
					count = count + 1
					if(count<=2):
						continue
					cols = line.strip().split('\t')
					if(cols[2]=='Delay'):
						delay_congestions[cols[0]] = int(cols[1])
					elif(cols[2]=='Bandwidth'):
						bandwidth_congestions[cols[0]] = int(cols[1])
			return delay_congestions, bandwidth_congestions
		except:
			return delay_congestions,bandwidth_congestions
	
	def saveCongestedTunnels(self,bandwidthCongestions,delayCongestions):
		congestionFile = self.config.get('WAECongestionDetection','congestedTunnelsFile')
		with open(congestionFile,'w+') as ifCmdFile:
			ifCmdFile.write('TunnelKey'+ '\t'+"CongestionOccuranceCount"+'\t'+"Delay/Bandwidth Violated"+'\n')
			for key,val in bandwidthCongestions.items():
				ifCmdFile.write(key+ '\t' + str(val)+ '\t'+ str("Bandwidth")+'\n')
			for key,val in delayCongestions.items():
				ifCmdFile.write(key+ '\t' + str(val)+ '\t'+ str("Delay")+'\n')
		self.log.info("Saved LSP's to CongestedTunnels file: ",congestionFile)	


	def updateFetchCongestionResWithReportedLsp(self,fetch_congestion_res,congested_lsps_to_be_reported,sla_violated_lsps_to_be_reported):
		self.log.debug("This method add only those LSPs in fetchcongestion response that are going in hybrid optimizer ")
		sla_violated_lsps_list=[]
		congested_lsps_list=[]
	
		try:
			congested_lsps_list=fetch_congestion_res['sr-fetch-congestion:output']['congested-lsps']
			for congested_lsp in list(congested_lsps_list):
				if(congested_lsp['lspName']+":::"+congested_lsp['lspSrcNode'] in congested_lsps_to_be_reported ):
					pass
				else:
					congested_lsps_list.remove(congested_lsp)
			fetch_congestion_res['sr-fetch-congestion:output']['congested-lsps']=congested_lsps_list
			self.log.debug("Generated fetch congestion response after removing those congested LSPs that are not in hybrid optimizer",json.dumps(fetch_congestion_res))
		except(Exception) as err:
			self.log.info("No bandwidth violated LSPs found")
			self.log.debug("Error",err)
			pass
	
		try:
			sla_violated_lsps_list=fetch_congestion_res['sr-fetch-congestion:output']['sla-violated-lsps']			
			for sla_violated_lsp in list(sla_violated_lsps_list):
				if(sla_violated_lsp['lspName']+":::"+sla_violated_lsp['lspSrcNode'] in sla_violated_lsps_to_be_reported ):
					pass
				else:
					sla_violated_lsps_list.remove(sla_violated_lsp)
			fetch_congestion_res['sr-fetch-congestion:output']['sla-violated-lsps']=sla_violated_lsps_list
			self.log.info("Generated fetch congestion response after removing those sla violated LSPs that are not in hybrid optimizer",json.dumps(fetch_congestion_res))
		except(Exception) as err:
			self.log.info("No SLA violated LSPs found ")
			self.log.debug("Error",err)	
			pass	
		
		if not (sla_violated_lsps_list or congested_lsps_list):
			return None
		else:
			return fetch_congestion_res
        
	def removeIgnoredLspsFromHybridOptimizerRes(self,hybdrid_optimizer_res,congested_lsps_to_be_ignored,sla_violated_lsps_to_be_ignored):		
		self.log.debug("This method removes all those LSPs that didn't cross threshold count ")
		try:
			sla_violated_lsps_list=hybdrid_optimizer_res['hybrid-optimizer:output']['delay-optimization-results']['delay-sla-violated-lsps']
			
			for sla_violated_lsp in list(sla_violated_lsps_list):
				if(sla_violated_lsp['lspName']+":::"+sla_violated_lsp['lspSrcNode'] in sla_violated_lsps_to_be_ignored):
					sla_violated_lsps_list.remove(sla_violated_lsp)
				else:
					pass
			hybdrid_optimizer_res['hybrid-optimizer:output']['delay-optimization-results']['delay-sla-violated-lsps']=sla_violated_lsps_list
			self.log.debug("Returned hybrid optimizer response after removing sla violated LSPs that didn't cross threshold count",json.dumps(hybdrid_optimizer_res))
		except(Exception) as err:
			self.log.info("No SLA violated LSps found after optimization")
			self.log.debug("Error",err)	

		try:
			contested_lsps_list=hybdrid_optimizer_res['hybrid-optimizer:output']['bandwidth-optimization-results']['congested-lsps']
			for congested_lsp in list(contested_lsps_list):
				if(congested_lsp['lspName']+":::"+congested_lsp['lspSrcNode'] in congested_lsps_to_be_ignored):
					contested_lsps_list.remove(congested_lsp)
				else:
					pass
					
			hybdrid_optimizer_res['hybrid-optimizer:output']['bandwidth-optimization-results']['congested-lsps']=contested_lsps_list
			self.log.debug("Returned hybrid optimizer response after removing congested LSPs that didn't cross threshold count",json.dumps(hybdrid_optimizer_res))
		except(Exception) as err:
			self.log.info("No congested  LSPs after optimization")
			self.log.debug("Error",err)
		return hybdrid_optimizer_res

	def run(self, net_name, input, output):
		my_helper=Helpers(self.log)
		fetch_congestion_res,threshold=self.getFetchCongestion(my_helper)
		if fetch_congestion_res is not None:
			self.callHybridOptimizer(fetch_congestion_res,threshold,my_helper)
		else:
			self.log.info("CloseLoopAutomation is running and there is no congestion in network!")
