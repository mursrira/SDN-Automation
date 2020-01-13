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
from com.cisco.wae.design import ServiceConnectionManager
from helpers import Helpers
from lspDetailsCache import LspDetailsCache
import xml.etree.ElementTree as ET
import json
import requests
from requests.auth import HTTPBasicAuth
from ncs.dp import Action
from helpers import Helpers
class SrTeDelayOptimizer(Application):

	def setup(self):
		self.log.info('delay-optimization service starting..')
		self.register_action('delay-optimization-action-point',SrTeDelayOptimizerAction, [])
		self.log.info('delay-optimization service started')

	def teardown(self):

		self.log.info('delay-optimization service stopped')


class SrTeDelayOptimizerAction(OpmActionBase):

	#@Action.action
	#def run(self, uinfo, name, kp, input, output):
	def run(self, net_name, input, output):
		self.update_start_status()
		SrTeDelayOptimizerActionImpl(self.log).run_delay_optmization(input, output.optimization_results)

class SrTeDelayOptimizerActionImpl:
	config = ConfigParser.RawConfigParser()

	def __init__(self, log):
		self.log = log

	def run_delay_optmization(self, input, output):
		lspsClassList = []

		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		
		# self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')
		self.nw_source = 'WMD'
		self.log.info("Got request for Delay Optimiaztion in network")
		start = time.time()
		#self.fetchClassLsps()
		self.delay_optimization_wmd(input, output)
		EndTime = time.time()
		self.log.info("Delay Optimization took ", (EndTime - start), " seconds")

	
	def delay_optimization_wmd(self, input, output):
	
		lspsOptimizationList = []
		for delay_lsp_to_be_optimized in input.delay_lsps_to_be_optimized:
			lspsOptimizationList.append(delay_lsp_to_be_optimized.lspSrcNode +'::'+delay_lsp_to_be_optimized.lspName)
		self.log.info("Operator Selected DELAY-OPT LSPs List is {}".format(lspsOptimizationList))

		my_helper = Helpers(self.log)
		#
		# To get the number of delay SLA violated VIP and non-VIP LSPs befor Optimization
		#
		vip_sla_voilated_count_bfr = 0
		non_vip_sla_voilated_count_bfr = 0
		try:
			response = my_helper.callFetchCongestion(input.post_delay_optimization_threshold)
			sla_violated_lsps_list = response['sr-fetch-congestion:output']['sla-violated-lsps']
			for delay_sla_voilated in list(sla_violated_lsps_list):
				if delay_sla_voilated["lspClass"] == "1":
					vip_sla_voilated_count_bfr = vip_sla_voilated_count_bfr + 1
				else:
					non_vip_sla_voilated_count_bfr = non_vip_sla_voilated_count_bfr + 1
		except Exception as ex:
			errMsg = "There is no SLA voileted LSPs for Delay optimization."
			self.log.error(errMsg)

		output.num_of_delay_sla_violated_vip_lsps_bfr = vip_sla_voilated_count_bfr
		output.num_of_delay_sla_violated_non_vip_lsps_bfr = non_vip_sla_voilated_count_bfr

		network = my_helper.read_network()
		network_model = my_helper.read_network()
		network_old = my_helper.read_network()

		lsps = network.model.lsps
		lsps_model = network_model.model.lsps
	
		optimize_only_lsps = []
		if len(lspsOptimizationList)>0:
			# Optimizing only selected LSPs
			for lsp_model in lsps_model:
				lspUniqueName = lsp_model.source.name+'::'+lsp_model.name
				if lspUniqueName in lspsOptimizationList:
					optimize_only_lsps.append(lsp_model.rpc_key)
			self.log.info("Only LSPs considered for Delay Optimization %s " %(optimize_only_lsps))
		else:
			# No explicit LSP provided, Optimizing all VIP LSPs
			lspsOptimizationList = LspDetailsCache.getInstance(self.log).getLSPsOfClass('1')
			for lsp_model in lsps_model:
				lspUniqueName = lsp_model.source.name+':::'+lsp_model.name
				sla = LspDetailsCache.getInstance(self.log).getLSPDelaySLA(lsp_model.source.name, lsp_model.name)
				#TODO _modelif llsps_models accessed sim no more works, gets prev path after optm
				if lspUniqueName in lspsOptimizationList and lsp_model.route.average_latency > sla:
				#if lspUniqueName in lspsOptimizationList:
					optimize_only_lsps.append(lsp_model.rpc_key)
			self.log.info("Only VIP LSPs considered for Delay Optimization %s " %(optimize_only_lsps))

		if(len(optimize_only_lsps) == 0):
			my_helper.fillSlaViolatedLsps([], output.delay_sla_violated_lsps)
			return

			'''self.log.error("Neither exclusive nor VIP LSPs are chosen for Delay Optimization, Hence narrowing optm to only first LSP in model")
			# This is done to avoid triggering Delay optm on whole network (optimize_only_lsps is empty)
			try:
				optimize_only_lsps.append(lsps_model[-1].rpc_key)
			except KeyError as e:
				self.log.fatal("No LSP in network {}".format(e))
				raise ValueError("No LSP in network, Can not run Optimizer")'''


		# Prepare Delay Optimizer
		serv = network.service_connection.rpc_service_connection
		toolMgr = serv.getToolManager()
		srteOptmizer = toolMgr.newSRTEOptimizer()
		
		options = com.cisco.wae.design.tools.SRTEOptimizerOptions(
			#utilThreshold = str(self.post_delay_optimization_threshold),
			optLSPs = optimize_only_lsps,
			metric = com.cisco.wae.design.tools.SRTEOptimizerMetricType.SR_TE_OPT_METRIC_DELAY,
			coreSL = False,lspTag = "SROpt")
		
		try:
			self.log.debug("Delay Optimization Options ",options)
			self.log.info("Invoking Delay Optimization")
			result=srteOptmizer.run(network.rpc_plan_network,options)
			self.log.debug("Delay Optimization result {}".format(result))

			changed_lsps = my_helper.get_rerouted_lsp_list(network, network_old)
			my_helper.fill_lsps_path(network_old, network,changed_lsps, output.delay_re_routed_lsps)
			#
			# To get the number of delay re-routed VIP and non-VIP LSPs after Optimization
			#
			vip_lsp_count = 0
			non_vip_lsp_count = 0
			for re_routed_lsp in output.delay_re_routed_lsps:
				if re_routed_lsp.lspClass == "1":
					vip_lsp_count = vip_lsp_count + 1
				else:
					non_vip_lsp_count = non_vip_lsp_count + 1
			output.num_of_delay_rerouted_non_vip_lsps = non_vip_lsp_count
			output.num_of_delay_rerouted_vip_lsps = vip_lsp_count

			lsps = network.model.lsps
			my_helper.fillSlaViolatedLsps(lsps, output.delay_sla_violated_lsps)
			#
			# To get the number of delay SLA violated VIP and non-VIP LSPs after Optimization
			#
			vip_sla_voilated_count = 0
			non_vip_sla_voilated_count = 0
			for delay_sla_voilated in output.delay_sla_violated_lsps:
				if delay_sla_voilated.lspClass == "1":
					vip_sla_voilated_count = vip_sla_voilated_count + 1
				else:
					non_vip_sla_voilated_count = non_vip_sla_voilated_count + 1

			output.num_of_delay_sla_violated_vip_lsps_aft = vip_sla_voilated_count
			output.num_of_delay_sla_violated_non_vip_lsps_aft = non_vip_sla_voilated_count

			toolMgr.removeTool(srteOptmizer)
						
		except Exception as ex:
			errMsg = "Unable to Delay optimize:: %s"%str(ex)
			self.log.error(errMsg)
			raise ValueError(errMsg)


