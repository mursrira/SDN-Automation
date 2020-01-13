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
import traceback
#from xml.etree.ElementTree import XML, fromstring, tostring,fromstringlist
from xml.etree import ElementTree

class SrTeBwOptimizer(Application):

	def setup(self):
		self.log.info('sr-te-bw-optimazation service starting..')
		self.register_action('bandwidth-optimization-action-point',SrTeBwOptimizerAction, [])
		self.log.info('sr-te-bw-optimazation service started')

	def teardown(self):
		self.log.info('sr-te-bw-optimazation service stopped')


class SrTeBwOptimizerAction(OpmActionBase):

	def run(self, net_name, input, output):
		self.update_start_status()
		SrTeBwOptimizerActionImpl(self.log).run_bw_optmization(input, output.optimization_results, None)


class SrTeBwOptimizerActionImpl:
	config = ConfigParser.RawConfigParser()

	def __init__(self, log):
		self.log = log

	def run_bw_optmization(self, input, output, network):

		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)

		# self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')
		self.nw_source = 'WMD'
		self.log.info("Got request for BW optimization in network")
		start = time.time()

		self.log.debug('Requested Optimization threshold is {}'.format(input.post_optimization_threshold))
		self.log.debug("exclude_vip_tunnels is {}".format(input.exclude_vip_tunnels))

		network = self.sr_te_bw_optimization_wmd(input, output, network)
		EndTime = time.time()

		self.log.info("BW Optimization took ", (EndTime - start), " seconds")
		return network


	def sr_te_bw_optimization_wmd(self,input, output, network):

		my_helper = Helpers(self.log)
		linkOffLoadStatus=input.link_off_load_status

                excludedNodeList = self.config.get('ExcludeNodesFromOpt', 'ExcludeNodeList')

		if network is None:
			network = my_helper.read_network()
			network_old = my_helper.read_network()
			#Created network_model in order send inputs of LSPs to optimizer, using netowrk obj to do that - optimizer functionality does not work
			network_model = my_helper.read_network()
		else:
			network_old = network.clone()

		ifaces = network.model.interfaces
		lsps = network.model.lsps
		lsps_model = network_model.model.lsps
		demands_model = network_model.model.demands

		lspsOptimizationList = []
		for lsp_to_be_optimized in input.lsps_to_be_optimized:
			lspsOptimizationList.append(lsp_to_be_optimized.lspSrcNode +'::'+lsp_to_be_optimized.lspName)
		self.log.debug("Operator Selected BW-OPT LSPs List is {}".format(lspsOptimizationList))


		linkOffLoadInterfaceList = []
		for interface_to_be_link_off in input.interfaces_to_be_optimized:
			linkOffLoadInterfaceList.append(interface_to_be_link_off.intfSrcNode +'::'+interface_to_be_link_off.intfName)
		self.log.debug("Operator Selected Link off load interface list is {}".format(linkOffLoadInterfaceList))


		interfacesToOpt = []

		#
		#Code to fix BGP peering interfaces and Link-off-load Use-case
		#
		for iface in ifaces:
			if 'ASN' in iface.node.name or 'ASN' in iface.opposite_interface.node.name:
				self.log.debug('Excluded interface {} from BW optimization'.format(iface.name))
				continue

			elif iface.node.name in excludedNodeList or iface.opposite_interface.node.name in excludedNodeList:
                                self.log.debug('Excluded interface {} from BW optimization'.format(iface.name))
                                continue

			else:
				if(linkOffLoadStatus==True):
					self.log.info("interface sourcenode::interfacename ",iface.node.name+"::"+iface.name)
					if iface.node.name+"::"+iface.name in linkOffLoadInterfaceList:
						#Reduce capacity of interface ,divide capacity by 10 power 6
						self.log.debug("Simulated capacity of interface {} is {}".format(iface.node.name+"::"+iface.name,iface.configured_capacity))
						self.log.debug("Reducing interface configured capacity by 10 to the power of 6 ")
						iface.configured_capacity=iface.configured_capacity/1000000000
						#iface.configured_capacity=iface.configured_capacity/1
						self.log.debug("Reduced configured capacity of interface {} is {}".format(iface.node.name+"::"+iface.name,iface.configured_capacity))
						interfacesToOpt.append(iface.rpc_key)
				else:
					interfacesToOpt.append(iface.rpc_key)

		self.log.debug('Links that are included in BW Optimization are {}'.format(interfacesToOpt))
	
		#Fixed demands btw CORE/IPOP <--> IPT,NEXUS Devices and btw IPT,NEXUS <--> IPT,NEXUS 	
		fixedDemands = []
		for demand in demands_model:
			if demand.source.name in excludedNodeList or demand.destination.name in excludedNodeList:
				fixedDemands.append(demand.rpc_key)
		#
		# Condition for deleting LSPs (Current Condition should present before fixed LSPs condition)
		#
		lspsDeleted = []

		if input.create_new_lsps is True:

			# To check the tunnel id range
			tunnel_id_start_value = self.config.get('WAEServer', 'TunnelIDStartValue')
			tunnel_id_stop_value = self.config.get('WAEServer', 'TunnelIDStopValue')

			for lsp_model in lsps_model:

				try :
					#TODO Improve-change logic based on customer recquirement
					tunnelId = int(lsp_model.name.strip().split('_t')[-1])
					self.log.debug("Tunnel ID is {}".format(tunnelId))
				except:
					self.log.debug("lsp {} is not SRTE (IOSXR 614 Code) so skipping it".format(lsp_model))
					continue

				if (tunnelId <= int(tunnel_id_stop_value)) and (tunnelId >= int(tunnel_id_start_value)):
				#TODO FOR AD-LAB
				#if tunnelId == 39:
					#Remove Above Lsp
					lsps.remove(lsp_model)
					lsps_model.remove(lsp_model)
					#Add to deleted LSPs List
					lspsDeleted.append(lsp_model.rpc_key)
					#lspsDeleted.append(lsp.name+':::'+lsp.source.node)

				self.log.debug('DELETED LSPs List are {}'.format(lspsDeleted))


		fixedLSPs = []
		#
		# Fixing all LSPs other than provided ones (input.lsps_to_be_optimized)
		#
		if len(lspsOptimizationList)>0:
			#lsp = network.model.lsps[{'source':srcNode, 'name':srcNode+'_t'+te_name}]
			for lsp_model in lsps_model:
				lspUniqueName	=	lsp_model.source.name+'::'+lsp_model.name
				if lspUniqueName not in lspsOptimizationList:
					fixedLSPs.append(lsp_model.rpc_key)
					#fixedLSPs.append(LSPKey(lsp.name,lsp.source.name))

			#TODO FOR AD-LAB
			'''for lsp in network.model.lsps:
				if lsp.lsp_type == 'rsvp' or lsp.name == 'to_SNG-EMIX-RA' or lsp.name == 'SKM-EMIX-RC_t13001':
					fixedLSPs.append(lsp.rpc_key)'''

		self.log.debug("LSPs excluded for BW Optimization %s " %(len(fixedLSPs)))


		#
		# Don't Re-Route VIP LSPs(FIX VIP LSPs, if exclude_vip_tunnels flag is True )
		#

		#Fetch Class 1 lsps from UOP local Cache
		lsps = LspDetailsCache.getInstance(self.log).getLSPsOfClass('1')
		for lsp in lsps:
			lsp_src_name  = lsp.split(':::')
			try:
				model_lsp = network.model.lsps[{'source':lsp_src_name[0], 'name':lsp_src_name[1]}]
				if input.exclude_vip_tunnels is True:
					if model_lsp.rpc_key not in fixedLSPs: 
						fixedLSPs.append(model_lsp.rpc_key)
				elif input.exclude_vip_tunnels is False:
					if model_lsp.rpc_key in fixedLSPs: 
						fixedLSPs.remove(model_lsp.rpc_key)
			except KeyError as e:
				self.log.error("Unable to find UOP reported LSP in WAE Model: ", e)
		self.log.debug("Exclude VIP LSPs -{} Action taken on - {} LSPs".format(input.exclude_vip_tunnels,len(fixedLSPs)))

		#
		#Re-route non VIP LSPS
		#
		#Fetch Class 0 lsps from UOP local Cache
		lsps = LspDetailsCache.getInstance(self.log).getLSPsOfClass('0')
		for lsp in lsps:
			lsp_src_name  = lsp.split(':::')
			try:
				model_lsp = network.model.lsps[{'source':lsp_src_name[0], 'name':lsp_src_name[1]}]
				if input.re_route_non_vip_lsps is False:
					if model_lsp.rpc_key not in fixedLSPs: 
						fixedLSPs.append(model_lsp.rpc_key)
				elif input.re_route_non_vip_lsps is True:
					if model_lsp.rpc_key in fixedLSPs: 
						fixedLSPs.remove(model_lsp.rpc_key)
			except KeyError as e:
				self.log.error("Unable to find UOP reported LSP in WAE Model: ", e)


		self.log.debug("Re-route Non-VIP LSPs -{} Action taken on - {} LSPs".format(input.exclude_vip_tunnels,len(fixedLSPs)))
		fixedLSPs = list(set(fixedLSPs))
		self.log.info("Total number of Fixed LSPs are {}".format(len(fixedLSPs)))
		
		self.log.info("Link Off Load Status ",linkOffLoadStatus)
		#Threshold by default is 80 (only for link off load use case)
		if(linkOffLoadStatus==True):
			thresholdValue=int(input.link_off_load_value)			
		else:
			thresholdValue=int(input.post_optimization_threshold)

		#
		# OPTIMIZER API CALL
		#
		serv = network.service_connection.rpc_service_connection
		toolMgr = serv.getToolManager()

		srtebwOptmizer = toolMgr.newSRTEBWOptimizer()
		self.log.info("ThresholdValue ",thresholdValue)
		options = com.cisco.wae.design.tools.SRTEBWOptimizerOptions(
			utilThreshold = thresholdValue,
			metric = com.cisco.wae.design.tools.SRTEBWOptimizerMetricType.SR_TE_BW_OPT_METRIC_DELAY,
			createLSPs = input.create_new_lsps,
			#createLSPs = True,
			fixedLSPs = fixedLSPs,
			optInterfaces = interfacesToOpt,
			fixedDemands = fixedDemands
			)

		###TRYBLOCK
		#try:
		self.log.debug("Invoked BW Optimization")
		self.log.debug('BW Options are - {}'.format(options))
		result	=	srtebwOptmizer.run(network.rpc_plan_network,options)
		self.log.debug("Optimization results ",result)
		self.log.debug("Newly created LSPs after Optimization are {}".format(result.newLSPs))

               	#TOOL EXECUTION Completed so removed it!
		toolMgr.removeTool(srtebwOptmizer)

		#
		#Filling output Yang
		#
		if result:
			#optResultObj =	output.optimization_results
			optResultObj =	output
			optResultObj.num_of_re_routed_lsps	  =	  result.numReroutedLSPs
			optResultObj.num_of_created_lsps = len(result.newLSPs)
			optResultObj.num_of_deleted_lsps = len(lspsDeleted)

			#Link off load
			if(linkOffLoadStatus==True):
				#After if it is less than 0 then send as 0 and if it is greater than 0 then devide it by 10 to the power of
				if(result.maxUtilAfter<0):
					optResultObj.max_intf_utilization_of_selected_intfs_aft_offload = str(0) + " %"
				else:
					maxUtilAfter=round(result.maxUtilAfter/1000000000,2)
					optResultObj.max_intf_utilization_of_selected_intfs_aft_offload = str(maxUtilAfter) + " %"
				
				#Devide it by 10 to the power of 6
				maxUtilBefore=round(result.maxUtilBefore/1000000000,2)
				optResultObj.max_intf_utilization_of_selected_intfs_bfr_offload =  str(maxUtilBefore) + " %"

				optResultObj.num_interfaces_selected_for_link_offload = len(result.congestedLinksBefore)
				optResultObj.num_selected_interfaces_cannot_be_offloaded = len(result.congestedLinksAfter)
			#Normal hybrid optimization
			else:
				optResultObj.max_intf_utilization_aft_optimization = str(result.maxUtilAfter) + " %"
				optResultObj.max_intf_utilization_bfr_optimization =  str(result.maxUtilBefore) + " %"
				optResultObj.num_congested_interfaces_bfr_optimization = len(result.congestedLinksBefore)
				optResultObj.num_congested_interfaces_aft_optimization = len(result.congestedLinksAfter)


		if optResultObj.num_of_created_lsps != 0 or optResultObj.num_of_re_routed_lsps != 0 \
			or optResultObj.num_of_deleted_lsps !=0:

			#CALL method to get New LSPS created

			newLspsCreated,lspsRerouted,lspsDeleted = \
			my_helper.get_created_or_changed_LSPs(result.modifiedLSPs,result.newLSPs,lspsDeleted)

			#FILL new LSP paths in output Yang
			reRoutedLspsObj = optResultObj.re_routed_lsps
			newLspsObj =  optResultObj.newly_created_lsps
			deletedLspsObj = optResultObj.deleted_lsps

			#
			#To fill newly created LSPs
			#
			if len(newLspsCreated)>0:
				my_helper.fill_lsps_path([],network,newLspsCreated,newLspsObj)

			#
			#TO fill re-routed LSPs
			#
			if len(lspsRerouted)>0:
				my_helper.fill_lsps_path(network_old,network,lspsRerouted,reRoutedLspsObj)


			#
			#To fill deleted LSPs
			#
			if len(optResultObj.num_of_deleted_lsps)>0:
				my_helper.fill_lsps_path(network_old,[],lspsDeleted,deletedLspsObj)


		self.log.info("Creating non off loaded interface list ")
		nonOffLoadedInterfaceList=[]
		for iface in ifaces:
							#Threshold => 0 as selected-link should be fully offloaded
			if(iface.simulated_utilization > 0 and iface.node.name +'::'+iface.name in linkOffLoadInterfaceList):
				nonOffLoadedInterfaceList.append(iface.node.name +'::'+iface.name)
			if iface.node.name+"::"+iface.name in linkOffLoadInterfaceList:
				iface.configured_capacity=(iface.configured_capacity*1000000000)
				self.log.debug("Increased configured_capacity of {} to {}".format(iface.node.name+"::"+iface.name,iface.configured_capacity))
		self.log.debug("After link-offload non-offloaded interface list is ",nonOffLoadedInterfaceList)


		#
		#Checking if Congested interfaces are still present,for link off load use case
		#
		if(linkOffLoadStatus==True):
			my_helper.helpers_get_congestion(ifaces, optResultObj,thresholdValue,nonOffLoadedInterfaceList,linkOffLoadStatus,network_old.model.interfaces)
		#Checking if Congested interfaces are still present,for hybrid optimizer use case
		elif((linkOffLoadStatus==False)):
			my_helper.helpers_get_congestion(ifaces, optResultObj, input.post_optimization_threshold,[],linkOffLoadStatus,None)
		#toolMgr.removeTool(srtebwOptmizer)

		return network
