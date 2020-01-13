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
from requests.auth import HTTPBasicAuth
import json

class hybridOptimizer(Application):
	def setup(self):
		self.log.info('hybridOptimizer service starting')
		self.register_action('optimizer-delay-action-point',optimizerDelay, [])
		self.register_action('optimizer-bandwidth-action-point',optimizerBandwidth, [])
		self.register_action('optimizer-delay-bandwidth-action-point',optimizerdelayBandwidth, [])
	
	def teardown(self):
		self.log.info('hybridOptimizer service stopped')

#DELAY
class optimizerDelay(OpmActionBase):
	def run(self, net_name, input, output):
		self.log.info('Invoking Hybrid Dealy Optimization for threshold: '+ str(input.post_delay_optimization_threshold))
		
		my_helper = Helpers(self.log)
		LspDetailsCache.getInstance(self.log).refreshLSPDetailsFromUOP()

		delay_optimizer =  srTeDelayOptimizer.SrTeDelayOptimizerActionImpl(self.log)
		with ncs.maapi.Maapi() as maapi_obj:
			with ncs.maapi.Session(maapi_obj, "admin", "system"):
				with maapi_obj.start_read_trans() as maapi_trans:
					root = ncs.maagic.get_root(maapi_trans)
					delay_action_input = root.wae__networks.wae__network[net_name].wae__opm.delay_optimization.run.get_input()
					delay_action_input.post_delay_optimization_threshold = int(input.post_delay_optimization_threshold)
					for lsp in input.delay_lsps_to_be_optimized:
						lsps_to_be_optimized = delay_action_input.delay_lsps_to_be_optimized.create()
						lsps_to_be_optimized.lspName = lsp.lspName
						lsps_to_be_optimized.lspSrcNode = lsp.lspSrcNode

					network = delay_optimizer.run_delay_optmization(delay_action_input, output.delay_optimization_results)
					# To add action status
					final_list = []
					result_dect = {}
					result_dect['re-routed'] = output.delay_optimization_results.delay_re_routed_lsps
					final_list.append(result_dect)
					my_helper.prep_hybrid_optimizer_output_invoke_uop_nso(final_list, input, output,"delay")

#BANDWIDTH
class optimizerBandwidth(OpmActionBase):
	def run(self, net_name, input, output):
		self.log.info('Invoking Hybrid BW Optimization for threshold: '+ str(input.post_optimization_threshold))
		self.log.debug("Link off load status ",input.link_off_load_status)
		my_helper = Helpers(self.log)
		LspDetailsCache.getInstance(self.log).refreshLSPDetailsFromUOP()

		bw_optimizer =  srTeBwOptimizer.SrTeBwOptimizerActionImpl(self.log)
		with ncs.maapi.Maapi() as maapi_obj:
			with ncs.maapi.Session(maapi_obj, "admin", "system"):
				with maapi_obj.start_read_trans() as maapi_trans:
					root = ncs.maagic.get_root(maapi_trans)
					bw_action_input = root.wae__networks.wae__network[net_name].wae__opm.bandwidth_optimization.run.get_input()
					if(input.link_off_load_status==False):
						bw_action_input.post_optimization_threshold = int(input.post_optimization_threshold)
					bw_action_input.exclude_vip_tunnels = input.exclude_vip_tunnels
					bw_action_input.create_new_lsps = input.create_new_lsps
					bw_action_input.re_route_non_vip_lsps = input.re_route_non_vip_lsps
					#Link off load
					bw_action_input.link_off_load_status=input.link_off_load_status
					bw_action_input.link_off_load_value=input.link_off_load_value


					for lsp in input.lsps_to_be_optimized:
						lsps_to_be_optimized = bw_action_input.lsps_to_be_optimized.create()
						lsps_to_be_optimized.lspName = lsp.lspName
						lsps_to_be_optimized.lspSrcNode = lsp.lspSrcNode


					#Link off load
					for interface in input.interfaces_to_be_optimized:
						interfaces_to_be_optimized = bw_action_input.interfaces_to_be_optimized.create()
						interfaces_to_be_optimized.intfName = interface.intfName
						interfaces_to_be_optimized.intfSrcNode = interface.intfSrcNode

					bw_action_output = root.wae__networks.wae__network[net_name].wae__opm.bandwidth_optimization.run.get_output()
					network = bw_optimizer.run_bw_optmization(bw_action_input, output.bandwidth_optimization_results, None)
					# To add action status
					final_list = []
					result_dect = {}
					if len(output.bandwidth_optimization_results.re_routed_lsps) >0:
						result_dect['re-routed'] = output.bandwidth_optimization_results.re_routed_lsps
						final_list.append(result_dect)
					if len(output.bandwidth_optimization_results.newly_created_lsps) >0:
						result_dect['created'] = output.bandwidth_optimization_results.newly_created_lsps
						final_list.append(result_dect)
					if len(output.bandwidth_optimization_results.deleted_lsps) >0:
						result_dect['deleted'] = output.bandwidth_optimization_results.deleted_lsps
						final_list.append(result_dect)

					my_helper.prep_hybrid_optimizer_output_invoke_uop_nso(final_list, input, output,"bandwidth")
					




#DELAY AND BANDWIDTH
class optimizerdelayBandwidth(OpmActionBase):
	def run(self, net_name, input, output):
		self.log.info('Invoking Hybrid Both Optimization for threshold: '+ str(input.post_optimization_threshold))
		
		my_helper = Helpers(self.log)
		LspDetailsCache.getInstance(self.log).refreshLSPDetailsFromUOP()

		delay_optimizer =  srTeDelayOptimizer.SrTeDelayOptimizerActionImpl(self.log)
		bw_optimizer =  srTeBwOptimizer.SrTeBwOptimizerActionImpl(self.log)

		with ncs.maapi.Maapi() as maapi_obj:
			with ncs.maapi.Session(maapi_obj, "admin", "system"):
				with maapi_obj.start_read_trans() as maapi_trans:
					root = ncs.maagic.get_root(maapi_trans)

					## Run Delay Optimizer
					delay_action_input = root.wae__networks.wae__network[net_name].wae__opm.delay_optimization.run.get_input()
					delay_action_input.post_delay_optimization_threshold = int(input.post_optimization_threshold)
					for lsp in input.delay_lsps_to_be_optimized:
						lsps_to_be_optimized = delay_action_input.delay_lsps_to_be_optimized.create()
						lsps_to_be_optimized.lspName = lsp.lspName
						lsps_to_be_optimized.lspSrcNode = lsp.lspSrcNode

					network = delay_optimizer.run_delay_optmization(delay_action_input, output.delay_optimization_results)

					## Run BW Optimizer
					bw_action_input = root.wae__networks.wae__network[net_name].wae__opm.bandwidth_optimization.run.get_input()
					bw_action_input.post_optimization_threshold = int(input.post_optimization_threshold)
					bw_action_input.exclude_vip_tunnels = input.exclude_vip_tunnels
					bw_action_input.create_new_lsps = input.create_new_lsps
					bw_action_input.re_route_non_vip_lsps = input.re_route_non_vip_lsps
					
					for lsp in input.lsps_to_be_optimized:
						lsps_to_be_optimized = bw_action_input.lsps_to_be_optimized.create()
						lsps_to_be_optimized.lspName = lsp.lspName
						lsps_to_be_optimized.lspSrcNode = lsp.lspSrcNode
					bw_action_output = root.wae__networks.wae__network[net_name].wae__opm.bandwidth_optimization.run.get_output()
					network = bw_optimizer.run_bw_optmization(bw_action_input, output.bandwidth_optimization_results, network)

			
					self.log.debug("Delay rerouted: {}".format(len(output.delay_optimization_results.delay_re_routed_lsps)))
					self.log.debug("BW rerouted: {}".format(len(output.bandwidth_optimization_results.re_routed_lsps)))
					
					# To add action status
					final_list = []
					result_dect = {}
					if len(output.bandwidth_optimization_results.re_routed_lsps) >0 or len(output.delay_optimization_results.delay_re_routed_lsps) >0:
						final_rerouted_list = []
						final_rerouted_list.extend(output.delay_optimization_results.delay_re_routed_lsps)
						final_rerouted_list.extend(output.bandwidth_optimization_results.re_routed_lsps)
						result_dect['re-routed'] = final_rerouted_list
						final_list.append(result_dect)
						self.log.debug("Both rerouted: {}".format(len(final_rerouted_list)))
					if len(output.bandwidth_optimization_results.newly_created_lsps) >0:
						result_dect['created'] = output.bandwidth_optimization_results.newly_created_lsps
						final_list.append(result_dect)
					if len(output.bandwidth_optimization_results.deleted_lsps) >0:
						result_dect['deleted'] = output.bandwidth_optimization_results.deleted_lsps
						final_list.append(result_dect)

					my_helper.prep_hybrid_optimizer_output_invoke_uop_nso(final_list, input, output,"bothDelayAndBanwidth")
