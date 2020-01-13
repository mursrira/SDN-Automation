from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
from lspDetailsCache import LspDetailsCache
from contextlib import contextmanager
import com.cisco.wae.design
import threading
import ConfigParser
import time
import re
import subprocess
from com.cisco.wae.design import ServiceConnectionManager
from com.cisco.wae.opm.network.model.lsp.key import LSPKey
import xml.etree.ElementTree as ET
import ncs
import traceback
from ncs.dp import Action
import requests
import smtplib
from requests.auth import HTTPBasicAuth
import json,os
from datetime import datetime

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------
class error(Exception):
	pass

class InterfaceList:
	def __init__(self, intf=None):
		self.intf = intf
		self.next = None

class Helpers(object):

	final_tunnel_id = 0
	config = ConfigParser.RawConfigParser()

	def __init__(self,log):
		self.log = log
		self.headers = {
			'content-type': "application/vnd.yang.operation+json"
			}
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)

	def helpers_get_congestion(self, ifaces, output, interfaceUtilThreshold,nonOffLoadedInterfaceList,linkOffLoadStatus,oldnetwork_interfaces):

		congestedLsps = []
		congested_lsp_if_mapping = {}

                excludedNodeList = self.config.get('ExcludeNodesFromOpt', 'ExcludeNodeList')
                self.log.debug('excludedNodeList {} '.format(excludedNodeList))
		#
		#Old network interfaces list
		#
		self.log.info("Creating interfaces dict of old network/modified network")
		try:
			oldInterfaces = oldnetwork_interfaces
			interfcesDict={}
			for iface in oldInterfaces:
				interfcesDict[iface.node.name+"::"+iface.name]=round(iface.simulated_utilization,2)
			self.log.info("Modified interface dict ",interfcesDict)
		except(Exception)as err:
			self.log.error("Error@Creating interfaces dict of old network/modified network ",err)
			pass

		self.log.debug("List of selected interfaces for link off load ",nonOffLoadedInterfaceList)
		for iface in ifaces:
			congeste_if_count = 0
			if 'ASN' in iface.node.name or 'ASN' in iface.opposite_interface.node.name:
				self.log.debug('skipped interface {} as it is a BGP peering Link'.format(iface.name))
				continue
                        elif iface.node.name in excludedNodeList or iface.opposite_interface.node.name in excludedNodeList:
                                self.log.debug('skipped node {} : remote node {}'.format(iface.node.name,iface.opposite_interface.node.name))
                                continue


			if(type(iface.simulated_utilization) is float):

				interfaceName = iface.name
				interfaceNodeName = iface.node.name
				interfaceDstNodeName = iface.opposite_interface.node.name
				#measuredTraffic = round(iface.measured_traffic,2)
				measuredTraffic = iface.measured_traffic
				configuredCapacity = iface.configured_capacity
				routed_lsps = iface.lsps_routed_through
				#measuredUtilization = round(iface.measured_utilization,2)
				measuredUtilization = iface.measured_utilization
				simulatedUtilization = round(iface.simulated_utilization,2)

				if(linkOffLoadStatus==True and nonOffLoadedInterfaceList != []):
					routed_lsps = []
					if (iface.node.name+"::"+iface.name in nonOffLoadedInterfaceList) \
					and (simulatedUtilization > 0):
						self.log.debug("Found non-offloaded interface ifaceNode {} ifaceName {}" \
						.format(iface.node.name,iface.name))
						self.createInterfaceForOutput(iface,"non_off_loaded_interfaces",output)
						continue

				if iface.simulated_utilization >=interfaceUtilThreshold:
					congeste_if_count = congeste_if_count + 1

					#
					#PUSH non off-loaded interface to output yang
					#
					if(linkOffLoadStatus==True):
						routed_lsps = []
						if((iface.node.name+"::"+iface.name)in interfcesDict):
							if(simulatedUtilization==interfcesDict[iface.node.name+"::"+iface.name]):
								continue
					elif(linkOffLoadStatus==False):
						routed_lsps = iface.lsps_routed_through


					# PUSH congested interfaces to output yang,for hybrid optimizer use case
					# Placing createInterfaceForOutput method below,Helps in Handling correctly output for
					# congested interfaces when link-offload is enabled
					self.createInterfaceForOutput(iface,"congested_interfaces",output)


					for routed_lsp in routed_lsps:
						if routed_lsp not in congestedLsps and routed_lsp.lsp_type != 'rsvp':
						#if routed_lsp not in congestedLsps:
							congestedLsps.append(routed_lsp)

						# Creating Congested LSP -> Congested Interfaces Mapping
						str_routed_lsp = str(routed_lsp)
						if not (congested_lsp_if_mapping.get(str_routed_lsp)):
							congested_lsp_if_mapping[str_routed_lsp]=[]
						congested_lsp_if_mapping[str_routed_lsp].append(iface)

			else:
				self.log.warning("BW utilization not compared for interface", iface.node.name+":"+iface.name,", because its measured traffic is not known")

				#self.log.info(congested_lsp_if_mapping)
		#self.log.debug("output object is {}".format(returnCongestedInterfaces))

		self.log.warning("Found {} Congested Interfaces & {} Congested LSPs".format(congeste_if_count,len(congestedLsps)))

		for lsp in congestedLsps:
			lspClass = LspDetailsCache.getInstance(self.log).getLSPClass(lsp.source.name, lsp.name)
			lspTraffic = round(lsp.simulated_traffic,2)
			lspName = lsp.name
			lspSrcNode = lsp.source.name
			lspDstNode = lsp.destination.name
			lspRoute = lsp.route
			delay = lspRoute.average_latency
			delay_sla = LspDetailsCache.getInstance(self.log).getLSPDelaySLA(lspSrcNode, lspName)

			# Filling Congested LSPs Output yang
			returnCongestedLsps = output.congested_lsps.create()
			returnCongestedLsps.lspName =	lspName
			returnCongestedLsps.lspSrcNode	 =	 lspSrcNode
			returnCongestedLsps.lspDstNode	 =	 lspDstNode
			returnCongestedLsps.lspClass	=	lspClass
			returnCongestedLsps.traffic =	str(lspTraffic) + " Mbps"
			returnCongestedLsps.delay = str(delay) + " ms"
			if delay_sla != 'N/A':
				returnCongestedLsps.delay_sla = str(delay_sla) + " ms"
			else:
				returnCongestedLsps.delay_sla = str(delay_sla)

			###LSP --> Traversing through congested interfaces
			str_lsp = str(lsp)
			congestedInterfaces = congested_lsp_if_mapping.get(str_lsp)
			#self.log.info("LSP congeted Interfaces type is	 {}".format(type(congestedInterfaces)))

			for congestedInterface in congestedInterfaces:
				congestedInterfaceName	 =	congestedInterface.name
				congestedInterfaceNodeName	 =	 congestedInterface.node.name
				#self.log.info("dir is {}".format(dir(returnCongestedLsps.complete_path)))
				#self.log.info("dir is {}".format(dir(returnCongestedLsps.complete_path.interfaceKeys)))
				congestedInterfaceList = returnCongestedLsps.congested_path.interfaceKeys.create()
				#self.log.debug("dir of lsit1 is {}".format(dir(congestedInterfaceList)))
				congestedInterfaceList.intfSrcNode	 =	congestedInterfaceNodeName
				congestedInterfaceList.intfName	 =	 congestedInterfaceName

			###LSP --> Travelling through all interfaces
			if lsp.routed:
				lsp_route = lsp.route
				#interfaces = lsp.route.interfaces
				interfaces = self.sort_interfaces_for_lsp(lsp)

				#self.log.info("interfaces routed through are {} ".format(interfaces))
				lsp_hops = self.get_hops_from_interfaces_for_lsp(interfaces)
				for hop in lsp_hops:
					lspInterfaceList = returnCongestedLsps.complete_path.interfaceKeys.create()
					lspInterfaceList.intfSrcNode,lspInterfaceList.intfName = hop['intfSrcNode'], hop['intfName']
			else:
				self.log.info("LSP not routed %s" %(str(lsp)))
		return output

	def get_created_or_changed_LSPs(self, modifedLsps, newlyCreatedLsps, lspsDeleted):

		newLspsCreated = []
		lspsRerouted = []
		deletedLsps = []

		if len(lspsDeleted) > 0:
			for lspDeleted in lspsDeleted:
				# srcNode	= lspDeleted.strip().split(':::')[-1]
				# changedLspName = lspDeleted.strip().split(':::')[0]
				srcNode = lspDeleted.sourceKey.name
				changedLspName = lspDeleted.name
				#TODO
				#lspKeyObj = LSPKey(changedLspName, srcNode)
				lspKeyObj = changedLspName+':::'+srcNode
				# self.log.info(lspKeyObj)
				deletedLsps.append(lspKeyObj)

		if len(newlyCreatedLsps) > 0:
			for newlyCreatedLsp in newlyCreatedLsps:
				srcNode = newlyCreatedLsp.sourceKey.name
				changedLspName = newlyCreatedLsp.name
				#TODO
				#lspKeyObj = LSPKey(changedLspName, srcNode)
				lspKeyObj = changedLspName+':::'+srcNode
				newLspsCreated.append(lspKeyObj)

		if len(modifedLsps) > 0:
			for modifedLsp in modifedLsps:
				srcNode = modifedLsp.sourceKey.name
				changedLspName = modifedLsp.name
				#TODO
				#lspKeyObj = LSPKey(changedLspName, srcNode)
				lspKeyObj = changedLspName+':::'+srcNode
				if lspKeyObj not in newLspsCreated:
					lspsRerouted.append(lspKeyObj)
				else:
					self.log.debug('LSP --> {} is a Newly created LSP'.format(changedLspName))
		self.log.debug(
			'Newly created LSPs count {} re-routed LSPs count {} deleted LSPs count {}'.format(len(newLspsCreated),
																							   len(lspsRerouted),
																							   len(deletedLsps)))
		return newLspsCreated, lspsRerouted, deletedLsps

	def get_rerouted_lsp_list(self, network, network_old):
		data = str(network.model - network_old.model)
		self.log.debug("Changed NW : {}".format(data))
		if not data :
			return []

		nets = ET.fromstring(data)
		nets_tag = nets.tag

		ns=nets_tag.strip()
		ns=ns.split('networks')[0]
		#print('ns is {}'.format(ns))
		#ns='{http://cisco.com/ns/wae}'

		net = nets.find(ns+'network')
		model = net.find(ns+'model')
		nodes = model.find(ns+'nodes')


		nodes_list = nodes.findall(ns+'node')

		changed_lsps=[]

		for node in nodes_list:

			node_name = node.find(ns+'name').text
			self.log.debug("Parsing node_name: {}".format(node_name))
			lsps=node.find(ns+'lsps')
			self.log.debug("Parsing node_name:{} : {} lsps".format(node_name, len(lsps)))

			for lsp in lsps.iter(ns+'lsp'):

				lsp_name = lsp.find(ns+'name').text
				self.log.debug("Parsing node_name:{} :lsps {}: lsp {}".format(node_name, lsps, lsp_name))
				#lsp_src_plus_name = node_name+':::'+lsp_name
				#TODO
				#lsp_src_plus_name = LSPKey(lsp_name,node_name)
				#self.log.info(lsp_src_plus_name,dir(lsp_src_plus_name),type(lsp_src_plus_name))
				lsp_src_plus_name = lsp_name+':::'+node_name
				#lsp_list.append(lsp_name)
				changed_lsps.append(lsp_src_plus_name)
				#print("lsp is {}".format(lsp_name.text))

			#print(lsp_list)
			#changed_lsps[node_name]=lsp_list
		#print(changed_lsps)
		self.log.debug("Changed LSPs count: {}".format(len(changed_lsps)) )
		return changed_lsps

	def getStatusofLink(self, netint_tables):

		#Extract NetIntInterfaces Table
		for netint_table in netint_tables:
			if str(netint_table.name) == 'NetIntInterfaces':
				rows = netint_table.rows
				break
		#Return StatusDict
		statusDict = {}
		for row in rows:
			for (key, value) in zip(row.keys(),row.values()):
				if key == 'Node' or key == 'Interface' or key == 'NetIntAdminStatus' or key == 'NetIntOperStatus':
					if key == 'Node':
						try:
							node = value
						except:
							node = None
					if key == 'Interface':
						try:
							intf = value
							if 'tunnel-te' in intf or 'TU' in intf or 'SONET' in intf or \
								'Serial' in intf or 'PTP' in intf or 'POS' in intf or \
								'Null0' in intf or 'POS' in intf or 'MgmtEth' in intf or \
								'Loopback' in intf or 'dwdm' in intf:
								break
						except:
							intf  = None
					if key == 'NetIntAdminStatus':
						try:
							intfAdminStatus = value
						except:
							intfAdminStatus = None
					if key == 'NetIntOperStatus':
						try:
							intfOperStatus = value
						except:
							intfOperStatus = None

						statusDictKey = str(node) + ':::' + str(intf)
						statusDictValue = str(intfAdminStatus) + ':::' + str(intfAdminStatus)
						statusDict[statusDictKey] = statusDictValue
						break #AS Filled Dictionary
				else:
					continue

		return statusDict



	def fill_lsps_path(self, network_old, network, changed_lsps, output_list):

		# To get the tunnel id range and tunnel_id from config file
		tunnel_id_start_value = self.config.get('WAEServer', 'TunnelIDStartValue')
		tunnel_id_stop_value = self.config.get('WAEServer', 'TunnelIDStopValue')
		tunnel_id = self.get_next_tunnel_id()
		for lspKey in changed_lsps:

			lspObj = output_list.create()

			#
			# DELETE
			#
			if network == []:
				srcNode = lspKey.strip().split(':::')[1]
				changedLspName = lspKey.strip().split(':::')[0]
				#TODO
				#lsp_old = network_old.model.lsps[lspKey]
				for lsp_old in network_old.model.lsps:
					if lsp_old.name == changedLspName and lsp_old.source.name == srcNode:
						lsp_old = lsp_old
						break
				self.fill_lsp_path(lsp_old, lspObj)
				self.lsp_path_parsing(lsp_old, lspObj.deleted_lsp_path)
				lspObj.prev_delay = str(lsp_old.route.average_latency) + " ms"
				self.log.debug("LSP {}->{}'s Prev Route Routed{}".format(lspObj.lspSrcNode, lspObj.lspName, lsp_old.routed))
			#
			# CREATE
			#
			if network_old == []:
				# To check the tunnel id range
				if (int(tunnel_id) > int(tunnel_id_stop_value)) or (int(tunnel_id) < int(tunnel_id_start_value)):
					self.update_next_tunnel_id(tunnel_id_start_value)
					tunnel_id = self.get_next_tunnel_id()

				srcNode = lspKey.strip().split(':::')[1]
				changedLspName = lspKey.strip().split(':::')[0]
				#TODO
				#lspKey1 = LSPKey(changedLspName, srcNode)
				for lsp in network.model.lsps:
					if lsp.name == changedLspName and lsp.source.name == srcNode:
					#lsp = network.model.lsps[lspKey1]
						self.fill_lsp_path(lsp, lspObj)
						#lspObj.lspName = "WAE_" + lsp.name + "_t" + str(tunnel_id)
						#TODO only Handled if Tunnel is IOS-XR Device
						lspObj.lspName = lsp.source.name + "_t" + str(tunnel_id)
						self.lsp_path_parsing(lsp, lspObj.newly_created_lsp_path)
						lspObj.delay = str(lsp.route.average_latency) + " ms"
						self.log.debug("LSP {}->{}'s New Route Routed{}".format(lspObj.lspSrcNode, lspObj.lspName, lsp.routed))
						break

				tunnel_id = int(tunnel_id) + 1
				Helpers.final_tunnel_id = int(tunnel_id)
			#
			# RE-ROUTE
			#
			if network != [] and network_old != []:
				#TODO
				#lsp_old = network_old.model.lsps[lspKey]
				#lsp = network.model.lsps[lspKey]
				srcNode = lspKey.strip().split(':::')[1]
				changedLspName = lspKey.strip().split(':::')[0]
				for lsp_old in network_old.model.lsps:
					if lsp_old.name == changedLspName and lsp_old.source.name == srcNode:
						lsp_old = lsp_old
						break
				for lsp in network.model.lsps:
					if lsp.name == changedLspName and lsp.source.name == srcNode:
						lsp = lsp
						break

				# TODO Delay Optm was re-routing LSP even with same post optm path.
				if not self.is_actually_rerouted(lsp, lsp_old):
					self.log.warning(
						"Re-Reouted LSP {}->{} has same path, so ignoring in result".format(lsp.source.name, lsp.name))
					continue

				self.fill_lsp_path(lsp_old, lspObj)
				self.fill_lsp_path(lsp, lspObj)
				self.lsp_path_parsing(lsp_old, lspObj.original_path)
				self.lsp_path_parsing(lsp, lspObj.re_routed_opt_path)
				#TODO
				if lsp_old.route.average_latency == float('inf'):
					lspObj.prev_delay = str(5) + " ms"
				else:
					lspObj.prev_delay = str(lsp_old.route.average_latency) + " ms"
				lspObj.delay = str(lsp.route.average_latency) + " ms"
				self.log.debug(
					"LSP {}->{}'s Prev Route Routed{}".format(lspObj.lspSrcNode, lspObj.lspName, lsp_old.routed))
				self.log.debug("LSP {}->{}'s New Route Routed{}".format(lspObj.lspSrcNode, lspObj.lspName, lsp.routed))

	def fill_lsp_path(self, lsp, lspObj):

		lspObj.lspName = lsp.name
		lspObj.lspSrcNode = lsp.source.name
		lspObj.lspDstNode = lsp.destination.name
		lspObj.traffic = str(round(lsp.simulated_traffic, 2)) + " Mbps"
		lspRoute = lsp.route
		delay_sla = str(LspDetailsCache.getInstance(self.log).getLSPDelaySLA(lspObj.lspSrcNode, lspObj.lspName))
		if delay_sla != 'N/A':
			lspObj.delay_sla = str(delay_sla) + " ms"
		else:
			lspObj.delay_sla = str(delay_sla)
		lspObj.lspClass = LspDetailsCache.getInstance(self.log).getLSPClass(lspObj.lspSrcNode, lspObj.lspName)

	def is_actually_rerouted(self, lsp, lsp_old):
		interfaces_new = self.sort_interfaces_for_lsp(lsp)
		interfaces_old = self.sort_interfaces_for_lsp(lsp_old)
		if len(interfaces_new) != len(interfaces_old):
			self.log.debug("Re-Reouted LSP {}->{} has same different interface counts ".format(lsp.source.name, lsp.name) )
			return True
		for i in range(len(interfaces_new)):
			if_old = interfaces_old[i]
			if_new = interfaces_new[i]
			if(if_old.name !=  if_new.name or if_old.node.name != if_new.node.name):
				self.log.debug("Re-Reouted LSP {}->{} has different interfaces old {}:{} & new {}:{}".format(lsp.source.name, lsp.name, if_old.node.name, if_old.name, if_new.node.name, if_new.name))
				return True
		return False



	def lsp_path_parsing(self,lsp,lspObj):
		lsp_route = lsp.route
		#interfaces = lsp_route.interfaces
		#self.log.info("destination is {}".format(dir(lsp_route.model.segment_lists[0].hops[0].hop)))
		hop_count = 1
		interfaces = self.sort_interfaces_for_lsp(lsp)
		#interfaces = lsp.route.interfaces
		lsp_hops = self.get_hops_from_interfaces_for_lsp(interfaces)
		for hop in lsp_hops:
			hopObj = lspObj.hop.create()
			hopObj.step = hop['step']
			hopObj.intfName = hop['intfName']
			hopObj.intfSrcNode = hop['intfSrcNode']
			hopObj.ip_address = hop['ip_address']

	def get_hops_from_interfaces_for_lsp(self, interfaces):
		prev_interface = []
		lsp_hops = []
		for interface in interfaces:
			prev_parallel_if_counts = len(prev_interface)
			if prev_parallel_if_counts == 0:
				prev_interface.append(interface)
				continue
			if prev_parallel_if_counts>0 and prev_interface[prev_parallel_if_counts-1].node.name == interface.node.name:
				self.log.debug("Ola i am load sharing, handle me pls "+interface.node.name+':::'+interface.name)
				prev_interface.append(interface)
				continue
			else:
				self.process_next_hop(interface, prev_interface, lsp_hops)
		# Process last leftover entery/ies in prev_interfaces
		self.process_next_hop(interface, prev_interface, lsp_hops)
		return lsp_hops

	def process_next_hop(self, interface, prev_interface, lsp_hops):
		prev_parallel_if_counts = len(prev_interface)
		if prev_parallel_if_counts>1:
			next_node_ip = prev_interface[prev_parallel_if_counts-1].opposite_interface.node.ip_address
			self.log.debug("Load Sharing ended, Please use next hop with node_ip: {}".format(next_node_ip) )
			# Creating extra hop for all load shring that just ended
			lsp_hop = {}
			lsp_hop['step'] = len(lsp_hops)+1
			lsp_hop['intfName'] = "Mutiple"
			lsp_hop['intfSrcNode'] = prev_interface[prev_parallel_if_counts-1].node.name
			lsp_hop['ip_address'] = next_node_ip
			lsp_hops.append(lsp_hop)
			self.log.debug("LSP Hop {}".format(lsp_hop))
			#clearing up prev saved load shared interfaces
			prev_interface[:] = []
			prev_interface.append(interface)
		else:
			intf = prev_interface[0]
			prev_interface[:] = []
			lsp_hop = {}
			lsp_hop['step'] = len(lsp_hops)+1
			lsp_hop['intfName'] = intf.name
			lsp_hop['intfSrcNode'] = intf.node.name
			lsp_hop['ip_address'] = intf.ip_addresses[0].rsplit("/")[0]
			lsp_hops.append(lsp_hop)
			self.log.debug("LSP Hop {}".format(lsp_hop))
			prev_interface.append(interface)

	def sort_interfaces_for_lsp(self, lsp):
		unordered_interfaces = lsp.route.interfaces
		ordered_if_list = []
		ordered_interfaces = InterfaceList()

		index = len(unordered_interfaces) - 1
		while(len(unordered_interfaces)>0):
		#for interface in unordered_interfaces:
			if index<0:
				index = len(unordered_interfaces) - 1
			interface = unordered_interfaces[index]
			ordered_interfaces,isAdded = self.position_interfaces_for_lsp_in_linkedlist(interface, ordered_interfaces, lsp)
			index = index - 1
			if isAdded:
				unordered_interfaces.remove(interface)
			#self.print_ordered(ordered_interfaces)
		#converting Linked list to Flat list again
		while ordered_interfaces is not None:
			ordered_if_list.append(ordered_interfaces.intf)
			ordered_interfaces = ordered_interfaces.next
		return ordered_if_list

	def print_ordered(self, ordered_interfaces):
		count = 1
		while ordered_interfaces is not None:
			self.log.debug("ordered {}: {}".format(count, ordered_interfaces.intf))
			ordered_interfaces = ordered_interfaces.next
			count = count + 1

	def position_interfaces_for_lsp_in_linkedlist(self, interface, ordered_interfaces, lsp):
		#self.log.debug("Trying to position intf {}:{}".format(interface.node.name,interface.name))
		if ordered_interfaces.intf is None:
			ordered_interfaces.intf = interface
			return ordered_interfaces, True

		prev_interface = None
		first_node_of_ordered = ordered_interfaces
		while(ordered_interfaces is not None and interface.opposite_interface.node.name != ordered_interfaces.intf.node.name):
			#self.log.debug("Didn't find matching next, so moving on from {}:{}".format(ordered_interfaces.intf.node.name,ordered_interfaces.intf.name))
			prev_interface = ordered_interfaces
			ordered_interfaces = ordered_interfaces.next
		if(ordered_interfaces is not None):
			# Found next hop already present so inserting before it
			#self.log.debug("Found next hop already present so inserting before {}:{}".format(ordered_interfaces.intf.node.name,ordered_interfaces.intf.name))
			dummy_node	= InterfaceList(interface)
			dummy_node.next = ordered_interfaces

			if(prev_interface is not None):
				#inserting in middle somewhere
				prev_interface.next = dummy_node
				return first_node_of_ordered, True
			else:
				#inserting in middle somewhere
				return dummy_node, True
		else:
			if interface.opposite_interface.node.name == lsp.destination.name:
				#self.log.debug("Couldn't insert anywhere so far so appending at end")
				prev_interface.next = InterfaceList(interface)
				return first_node_of_ordered, True
		return first_node_of_ordered, False

	def fillSlaViolatedLsps(self,lsps,output):
		sla_violated_lsp_count = 0
		for lsp in lsps:
			lspRoute = lsp.route
			interfaces = self.sort_interfaces_for_lsp(lsp)
			delay = lspRoute.average_latency
			delay_sla = LspDetailsCache.getInstance(self.log).getLSPDelaySLA(lsp.source.name, lsp.name)

			if delay_sla !='N/A' and delay > float(delay_sla) :
				sla_violated_lsp_count = sla_violated_lsp_count + 1
				self.log.warning("SLA violated lsp ({}) with delay {}".format(lsp.name , delay))
				sla_violated_lsp = output.create()
				sla_violated_lsp.lspClass = LspDetailsCache.getInstance(self.log).getLSPClass(lsp.source.name, lsp.name)
				sla_violated_lsp.traffic = str(round(lsp.simulated_traffic,2)) + " Mbps"
				sla_violated_lsp.lspName = lsp.name
				sla_violated_lsp.lspSrcNode = lsp.source.name
				sla_violated_lsp.lspDstNode = lsp.destination.name
				sla_violated_lsp.delay = str(lspRoute.average_latency) + " ms"
				if delay_sla != 'N/A':
					sla_violated_lsp.delay_sla = str(delay_sla) + " ms"
				else:
					sla_violated_lsp.delay_sla = str(delay_sla)
				# Filling Path info
				#self.log.info("interfaces routed through are {} ".format(interfaces))
				lsp_hops = self.get_hops_from_interfaces_for_lsp(interfaces)
				for hop in lsp_hops:
					intfObj = sla_violated_lsp.complete_path.interfaceKeys.create()
					intfObj.intfName = hop['intfName']
					intfObj.intfSrcNode = hop['intfSrcNode']

		self.log.info("Found {} SLA violating LSPs".format(sla_violated_lsp_count))

	# final_changed_lsps_list --> contains - LSPs (created, deleted and re-routed)

	def prep_hybrid_optimizer_output_invoke_uop_nso(self, final_changed_lsps_list, input, output,requestType):

		try:
			if (len(final_changed_lsps_list) > 0):
				payload = self.generatePayload(final_changed_lsps_list, "dry-run")
				nso_payload = payload[0]
				uop_payload = payload[1]
				uop_patch_payload = payload[2]
				self.log.debug("NSO nso_payload: ", nso_payload)
				if (input.action_type == "dry-run"):
					output.result = self.invokeNsoAction(nso_payload, uop_payload, uop_patch_payload, "dry-run",None,None)
					res = output.result

				elif (input.action_type == "force-commit"):
					payload = self.generatePayload(final_changed_lsps_list, "commit")
					nso_payload = payload[0]
					uop_payload = payload[1]
					uop_patch_payload = payload[2]
					output.result = self.invokeNsoAction(nso_payload, uop_payload, uop_patch_payload, "commit",None,None)


				else:
					#action_type = commit
					res = self.invokeNsoAction(nso_payload, uop_payload, uop_patch_payload, "dry-run",None,None)
					if ((res) == (input.configs)):
						payload = self.generatePayload(final_changed_lsps_list, "commit")
						nso_payload = payload[0]
						uop_payload = payload[1]
						uop_patch_payload = payload[2]
						final_uop_payload = self.generateFinalUopPayload(uop_payload, res)
						#if input.link_off_load_status==False:
						if requestType =="delay":
							fetchCongestionResponse=self.callFetchCongestion(str(input.post_delay_optimization_threshold))
						if requestType =="bandwidth":
							fetchCongestionResponse=self.callFetchCongestion(str(input.post_optimization_threshold))
						if requestType =="bothDelayAndBanwidth":
							fetchCongestionResponse=self.callFetchCongestion(str(input.post_optimization_threshold))


						output.result = self.invokeNsoAction(nso_payload, final_uop_payload, uop_patch_payload, "commit",fetchCongestionResponse,output)
					else:
						output.result = "Please Re-run as Optimiation results are changed"
			else:
				output.result = "No LSPs RE-ROUTE/CREATE/DELETE is Possible, please Try Again with different parameters."
			# Added action_type and rollback_allowed
		except (KeyError, IndexError, ValueError, NameError) as err:
			output.result = err
			#raise err

	def generateUopPayload(self, lspSrcName, lspSrcNode, uop_prev_payload, uop_next_payload, output_status,
						   rollback_allowed):
		# uopPayload = "{ \"node_name\": \""+lspSrcName+"\",\"lsp_name\":\""+lspSrcNode+"\",\"prev_state\":"+uop_prev_payload+",\"new_state\":"+uop_next_payload+",\"action_type_status\":\""+output_status+"\",\"rollback_allowed\": \""+rollback_allowed+"\"}"
		uopPayload = {}
		uopPayload["node_name"] = lspSrcName
		uopPayload["lsp_name"] = lspSrcNode
		uopPayload["prev_state"] = uop_prev_payload
		uopPayload["new_state"] = uop_next_payload
		uopPayload["action_type_status"] = output_status
		uopPayload["rollback_allowed"] = rollback_allowed
		return uopPayload

	# Added  unique_id and rollback_allowed
	def	generateUopPatchPayload(self,unique_id,rollback_allowed):
		uopPayload = {}
		uopPayload["unique_id"] = unique_id
		uopPayload["rollback_allowed"] = rollback_allowed
		return uopPayload

	def generatePayload(self, final_list, action_type):


		try:

			self.log.debug("Generating Payload for UOP & NSO")
			### GENERATING THE PAYLOAD
			uop_complete_payload, nso_complete_payload, uop_complete_patch_payload = [], [], []
			payload,payloadvalue = {},{}

			routed_lsps,created_lsps,deleted_lsps = [],[],[]

			if (action_type == "dry-run"):
				payloadvalue["action-type"] = "dry-run"
			else:
				payloadvalue["action-type"] = "commit"

			for result_lsp_dict in final_list:

				if 're-routed' in result_lsp_dict:
					routed_lsps = result_lsp_dict['re-routed']
				if 'created' in result_lsp_dict:
					created_lsps = result_lsp_dict['created']
				if 'deleted' in result_lsp_dict:
					deleted_lsps = result_lsp_dict['deleted']

			if len(routed_lsps) > 0:
				compt_payload = self.generateCompetlePayload(routed_lsps, 're-routed')
				nso_complete_payload.extend(compt_payload[0])
				uop_complete_payload.extend(compt_payload[1])
				uop_complete_patch_payload.extend(compt_payload[2])
			if len(created_lsps) > 0:
				compt_payload = self.generateCompetlePayload(created_lsps, 'created')
				#TODO Uncomment After NSO CODE FIX For Create LSP Feature
				nso_complete_payload.extend(compt_payload[0])
				uop_complete_payload.extend(compt_payload[1])
				uop_complete_patch_payload.extend(compt_payload[2])
			if len(deleted_lsps) > 0:
				compt_payload = self.generateCompetlePayload(deleted_lsps, 'deleted')
				nso_complete_payload.extend(compt_payload[0])
				uop_complete_payload.extend(compt_payload[1])
				uop_complete_patch_payload.extend(compt_payload[2])

			uop_complete_payload = str(json.dumps(uop_complete_payload, skipkeys=True))
			uop_complete_patch_payload = str(json.dumps(uop_complete_patch_payload, skipkeys=True))
			self.log.debug("UOP Payload Generated for invocation: ", uop_complete_payload)
			self.log.debug("UOP Patch Payload Generated for invocation: ", uop_complete_patch_payload)
			payloadvalue["te-interfaces"] = nso_complete_payload
			payload["input"] = payloadvalue
			payload = str(json.dumps(payload, skipkeys=True))
			self.log.debug("NSO PAYLOAD: ", payload)

			return [payload, uop_complete_payload, uop_complete_patch_payload]
		except (KeyError, IndexError, ValueError, NameError) as err:
			raise ValueError(err)
		except Exception as e:
			raise Exception("ISSUE Occured @ generatePayload method")


	def generateCompetlePayload(self, opt_results, action_type_status):
		uop_payload, nso_payload, uop_patch_payload = [], [], []
		response = ""
		count = 0
		for out_routed in opt_results:

			new_path_payload,uop_new_path_payload,orig_path_payload,uopPayload,uopPatchPayload = {},{},{},{},{}
			te_name = out_routed.lspName
			srcNode = out_routed.lspSrcNode
			destNode = out_routed.lspDstNode

			if ("tunnel-te" in te_name):
				# Handling tunnel-te37 kind of tunnels
				te_number = te_name.rsplit("-")
				te_nu = te_number[len(te_number) - 1]
				te_nu = te_nu[2:]
			else:
				# Handling srcNode_t37 kind of tunnels
				te_number = te_name.rsplit("_")
				te_nu = te_number[len(te_number) - 1]
				te_nu = te_nu[1:]

			#
			#COMMON VALUES
			#
			new_path_payload["te-name"] = uop_new_path_payload["te-name"] = orig_path_payload["te-name"] = te_nu
			new_path_payload["srcNode"] = uop_new_path_payload["srcNode"] = orig_path_payload["srcNode"] = srcNode
			new_path_payload["destNode"] = uop_new_path_payload["destNode"] = orig_path_payload["destNode"] = destNode
			new_path_payload["pathOption"] =  uop_new_path_payload["pathOption"] = orig_path_payload["pathOption"] = "1"

			# orig_path_payload = uop_new_path_payload

			# To check the re_routed_opt_path and original_path persent in final list.
			if action_type_status == 're-routed':
				rollback_allowed = 'true'
				#To set the operation type for NSO payload
				new_path_payload["operation-type"] = 're-routed'
				re_routed_hoplist = []
				uop_re_routed_hoplist = []
				for re_routed_hop_node in out_routed.re_routed_opt_path.hop:
					re_routed_hopsDict = {}
					uop_re_routed_hopsDict = {}

					#
					#COMMON VALUES
					#
					re_routed_hopsDict["step"] = uop_re_routed_hopsDict["step"] = re_routed_hop_node.step
					re_routed_hopsDict["ipaddress"] = uop_re_routed_hopsDict["ipaddress"] = re_routed_hop_node.ip_address
					# re_routed_hopsDict["intfSrcNode"] = str(re_routed_hop_node.intfSrcNode)
					uop_re_routed_hopsDict["intfSrcNode"] = str(re_routed_hop_node.intfSrcNode)

					re_routed_hoplist.append(re_routed_hopsDict)
					uop_re_routed_hoplist.append(uop_re_routed_hopsDict)

				new_path_payload["hop"],uop_new_path_payload["hop"] = re_routed_hoplist,uop_re_routed_hoplist

				self.log.debug("NEW PATH PAYLOAD: ", new_path_payload)
				hoplist = []
				for hop_node in out_routed.original_path.hop:
					hopsDict = {}
					hopsDict["step"] = hop_node.step
					hopsDict["ipaddress"] = hop_node.ip_address
					hopsDict["intfSrcNode"] = str(hop_node.intfSrcNode)
					hoplist.append(hopsDict)
				orig_path_payload["hop"] = hoplist

				self.log.debug("ORIGINAL PATH PAYLOAD: ", orig_path_payload)
				uopPayload = self.generateUopPayload(srcNode, te_name, orig_path_payload, uop_new_path_payload,action_type_status, rollback_allowed)
				uop_payload.append(uopPayload)
				nso_payload.append(new_path_payload)

			# To check the newly_created_lsp_path persent in final list.
			if action_type_status == 'created':
				rollback_allowed = 'true'
				#To set the operation type for NSO payload
				new_path_payload["operation-type"] = 'created'
				new_path_payload["pathName"] = "wae_"+te_name
				uop_pre_path_payload = {}
				hoplist = []
				newly_created_hopslist = []
				for hop_node in out_routed.newly_created_lsp_path.hop:
					newly_created_hopsDict = {}
					hopsDict = {}

					#
					#COMMON VALUES
					#
					newly_created_hopsDict["step"] = hopsDict["step"] = hop_node.step
					newly_created_hopsDict["ipaddress"] = hopsDict["ipaddress"] = hop_node.ip_address
					hopsDict["intfSrcNode"] = str(hop_node.intfSrcNode)

					newly_created_hopslist.append(newly_created_hopsDict)
					hoplist.append(hopsDict)
				new_path_payload["hop"],uop_new_path_payload["hop"] = newly_created_hopslist,hoplist

				self.log.debug("NEW CREATED PATH PAYLOAD: ", new_path_payload)
				uopPayload = self.generateUopPayload(srcNode, te_name, uop_pre_path_payload, uop_new_path_payload, action_type_status,
													 rollback_allowed)
				uop_payload.append(uopPayload)
				nso_payload.append(new_path_payload)

			#
			# DELETED LSP (PUSHING TO UOP ONLY)
			#
			# To check the deleted_lsp_path persent in final list.
			if action_type_status == 'deleted':
				rollback_allowed = 'false'
				#To set the operation type for NSO payload
				new_path_payload["operation-type"] = 'deleted'
				hopsDict = {}
				hoplist = []
				uop_next_path_payload = {}
				# To Retrieve Hops Details for NSO payload and Next Hops Details for UOP payload
				for hop_node in out_routed.deleted_lsp_path.hop:
					hopsDict["step"] = hop_node.step
					hopsDict["ipaddress"] = hop_node.ip_address
					hopsDict["intfSrcNode"] = str(hop_node.intfSrcNode)
					hoplist.append(hopsDict)
				orig_path_payload["hop"] = hoplist
				self.log.debug("ORIGINAL DELETED PATH PAYLOAD: ", orig_path_payload)
				uopPayload = self.generateUopPayload(srcNode, te_name, orig_path_payload, uop_next_path_payload, action_type_status,
													 rollback_allowed)
				# To get the unique_id for created lsp from rollback table 
				# where action_type_status is created and rollback_allowed is True
				if response == "" and count == 0:
					response = self.invokeUOPRestApi("history", "GET", None)
					count = count+1
					self.log.debug("GET History Response: ", response)
				# To check the response data is not empty and  success is true
				if response['meta']['success'] and response["data"] != []:
					# Retrieve data from response
					for element in response["data"]:
						self.log.debug("LSP name from Rollback table:",element["lsp_name"])
						lspname = element["lsp_name"]
						lsp_te_number = lspname.rsplit("_t")
						lsp_te_nu = lsp_te_number[len(lsp_te_number) - 1]
						#lsp_te_nu = lsp_te_nu[1:]
						#To get LSPs unique_id if te_nu match with response data lsp_te_nu
						if lsp_te_nu == te_nu:
							unique_id= element["unique_id"]
							self.log.debug("unique_id : ", unique_id)
							# To get UOP patch payload to disable existing created LSP
							uopPatchPayload = self.generateUopPatchPayload(unique_id,rollback_allowed)
				# To Prepare complete UOP and NSO payload for all LSPs
				uop_payload.append(uopPayload)
				uop_patch_payload.append(uopPatchPayload)
				nso_payload.append(new_path_payload)

		return [nso_payload, uop_payload, uop_patch_payload]

	def invokeNsoAction(self, nso_payload, uop_payload, uop_com_patch_payload, action_type,input,output):
		# FETCH FROM Config File

		#
		# SAME Method is invoked during dry-run/commit to devices using NSO
		#

		self.log.debug("Preparing  NSO call: ")
		nsoVmIp = self.config.get('NSOServer', 'ServerRestURL')
		restApiUserName = self.config.get('NSOServer', 'RestAPIUserName')
		restApiPassword = self.config.get('NSOServer', 'RestAPIUserPass')


		url = nsoVmIp + "/api/running/action/lsp-re-router/_operations/"
		response = requests.request("POST", url, auth=HTTPBasicAuth(restApiUserName, restApiPassword),headers=self.headers, data=nso_payload, verify=False)
		res_json = json.loads(response.content, strict=False)

		if(response.status_code==200):
			self.log.info("Rest response from OPM :" + response.content)
			res_json = json.loads(response.content, strict=False)
			self.log.debug("NSO LSP-RE-ROUTE ACTION Result - {}".format(res_json['lsp-re-route:output']['result']))
			self.log.debug("NSO LSP-RE-ROUTE ACTION Message {} ".format(res_json['lsp-re-route:output']['message']))

			if(res_json['lsp-re-route:output']['result']):
				self.log.info("NSO Response SUCCESS")
				result = res_json['lsp-re-route:output']['message']
				if(action_type == "commit"):
					#if input is not None:
					hybdrid_optimizer_res=self.prepareYangToJsonForManualEmailNotification(input,output)
					self.log.debug("Hybrid optimizer parsed response for sendEmailNotification ",hybdrid_optimizer_res)
					fetch_congestion_res=input
					self.log.debug("Fetch congestion response for sendEmailNotification",fetch_congestion_res)
					if(hybdrid_optimizer_res is not None):
						self.sendEmailNotification(fetch_congestion_res,hybdrid_optimizer_res,None)
					

					result = res_json['lsp-re-route:output']['message']
					self.log.info("Pushing Roll Back enteries to UOP....")
					# NSO Committed successfully, now pushing to UOP for rollback
					resp = self.invokeUOPRestApi('history', 'POST', uop_payload)
					self.log.debug('Response from UOP recieved : {}'.format(resp))
					self.log.debug('Response from UOP {} and the message is {}'.format(resp['meta']['success'],resp['meta']['info']))

					# To call PATCH method for rollback
					if uop_com_patch_payload != '' and len(uop_com_patch_payload) > 0:
						self.invokeUOPRestApi('history', 'PATCH', uop_com_patch_payload)



					#
					#To Update the tunnel id in NextTunnelIdFile
					#
					self.update_next_tunnel_id(Helpers.final_tunnel_id)
					
					

				else:
					self.log.info("NSO dry-Run was invoked! so No Call to UOP in-order to update rollback entries")
					result = res_json['lsp-re-route:output']['message']
				return result
		else:
			try:
				#STANDARD NSO ERROR
				raise Exception(res_json["errors"]["error"][0]["error-message"])
			except Exception as e:
				raise Exception(e)

			
	def invokeUOPRestApi(self, url, reqType, payload):

		uopVmIp = self.config.get('UOPServer', 'ServerRestURL')
		restApiUserName = self.config.get('UOPServer', 'RestAPIUserName')
		restApiPassword = self.config.get('UOPServer', 'RestAPIUserPass')

		self.log.debug("Type of Payload to UOP {} ".format(type(payload)))
		# payload = str(json.dumps(payload))
		# self.log.debug("Sending POST Payload to UOP {} ".format(payload))

		response = ""

		url = uopVmIp + "/api/lsp/optimization/" + url
		if 'link_utilization_wae' in url:
			url = uopVmIp+"/api/ipt_customers/link_utilization_wae/"
		if 'get_threshold_cross_count' in url:
			url = uopVmIp+"/api/company_config"

		if 'company_config' in url:
			url = uopVmIp+"/api/company_config"

		if 'notification' in url:
			url = uopVmIp + "/api/lsp/notification"

		if 'get_lsp_email' in url:
			url = uopVmIp + "/api/lsp/optimization/get_lsp_email"

		if 'capacity_inventory_wae' in url:
			self.headers = {
			'content-type': "application/json"
			}
			url = uopVmIp + "/api/capacity_inventory_wae/"


		if reqType == "GET":
			# To get the created LSP details from history based on search criteria
			if 'history' in url:
				# To Set the search criteria in header
				headers = self.headers
				headers['search-fields'] = '{"action_type_status": "created","rollback_allowed": true}'

				url = uopVmIp + "/api/lsp/optimization/history"
				self.log.debug("Header to UOP {} ".format(headers))
				response = requests.request(reqType, url, auth=HTTPBasicAuth(restApiUserName,restApiPassword), headers=headers,verify=False)
			else:
				response = requests.request(reqType, url, auth=HTTPBasicAuth(restApiUserName,restApiPassword), headers=self.headers,verify=False)

		elif reqType == "POST":
			self.log.debug("Sending POST Payload to UOP {}->{} ".format(url, payload))
			response = requests.request(reqType, url, auth=HTTPBasicAuth(restApiUserName, restApiPassword),data=payload, headers=self.headers,verify=False)
		elif reqType == "PATCH":
			self.log.debug("Sending PATCH Payload to UOP {}->{} ".format(url, payload))
			response = requests.request(reqType, url, auth=HTTPBasicAuth(restApiUserName, restApiPassword),data=payload, headers=self.headers,verify=False)

		return json.loads(response.content, strict=False)

	def invokeWaeOpmRestApi(self, url, reqType, payload):

		waeVmIp = self.config.get('WAEServer', 'OPMRestAPIServer')
		restApiUserName = self.config.get('WAEServer', 'OPMRestAPIUserName')
		restApiPassword = self.config.get('WAEServer', 'OPMRestAPIUserPass')
		networkName = self.config.get('WAEServer', 'Traffic-NIMO-NetworkName')

		#TODO
                if 'plan-archive/list' in url:
                        networkName = self.config.get('WAEServer', 'Inventory-NIMO-NetworkName')

		url = waeVmIp+"/api/running/networks/network/"+networkName+"/"+url+"/"+"_operations"
		#url - plan-archive/list

		if reqType == "POST":

			self.log.debug("Sending POST Payload to WAE {}->{} ".format(url, payload))
			response = requests.request(reqType, url, auth=HTTPBasicAuth(restApiUserName, restApiPassword),data=payload, headers=self.headers, verify=False)
			try:
				res_json = json.loads(response.content, strict=False)
			except(Exception) as err:
				self.log.debug("No Congestion found in network ",err)
				res_json=None

		try:
			if(response.status_code==200 or response.status_code==204):
				self.log.debug("Response Received {} ".format(res_json))
				try:
					out = json.loads(response.content)					
					self.log.debug("Rest response from WAE Server :" + response.content)
				except(Exception) as err:
					out=None
					self.log.debug('Response invoking WAE API is empty so set{}'.format(out))
				
				self.log.debug("JSON Rest response from WAE Server : " + str(out))

				if 'plan-archive/list' in url:
					self.log.info("Plan-Files Retrevial Status from OPM API is {} and message is {}".format(out['cisco-wae-archive:output']['status'], out['cisco-wae-archive:output']['message']))
					return out
				elif 'plan-archive/list' not in url:
					return out
				else:
					self.log.error("Requested url - {} is not supported".format(url))
			else:
				#STANDARD NSO ERROR Message
				raise Exception(res_json['errors']['error'][0]['error-message'])
		except(Exception) as err:
			raise Exception(err)
		else:
			self.log.error("Requested Type method {}is not present for API {}".format(reqType, url))

	def read_network(self):
		return TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)

	# To get the Tunnel id
	def get_next_tunnel_id(self):
		tunnel_id_file = self.config.get('WAEServer', 'NextTunnelIdFile')
		if not os.path.exists(tunnel_id_file):
			tunnel_id_start_value = self.config.get('WAEServer', 'TunnelIDStartValue')
			with open(tunnel_id_file, 'w') as ifCmdFile:
				ifCmdFile.write(tunnel_id_start_value + "\n")

		with open(tunnel_id_file) as ifCmdFile:
			content = ifCmdFile.readlines()
			for line in content:
				tunnel_id = str(line).rstrip()
				return tunnel_id
	# To update the tunnel_id into Tunnel id file
	def update_next_tunnel_id(self, tunnel_id):
		next_tunnel_id = str(int(tunnel_id))
		tunnel_id_file = self.config.get('WAEServer', 'NextTunnelIdFile')
		with open(tunnel_id_file, 'w') as ifCmdFile:
			ifCmdFile.write(next_tunnel_id + "\n")
		self.log.info("Updated nexttunnel_id to: ", next_tunnel_id)

	def sendEmailNotification(self, fetch_congestion_res, hybdrid_optimizer_res,err):
		self.log.info("Invoking sendEmailNotification(self, fetch_congestion_res, hybdrid_optimizer_res)...")
		self.log.info("This method sends Email notification")
		try:
			emailContent = ""
			out ='<html>'
			out=out+'<head><style type=text/css>'
			out=out+'table.gridtable {font-family: verdana,arial,sans-serif;'
			out=out+'font-size:12px;color:#333333;'
			out=out+'border-width: 1px;'
			out=out+'border-color: #666666;'
			out=out+'border-collapse: collapse;}'
			out=out+'table.gridtable th {border-width: 1px;'
			out=out+'padding: 8px;'
			out=out+'border-style: solid;'
			out=out+'border-color: #666666;'
			out=out+'background-color: #dedede;}'
			out=out+'table.gridtable td {border-width: 1px;'
			out=out+'padding: 8px;'
			out=out+'border-style: solid;'
			out=out+'border-color: #666666;'
			out=out+'background-color: #ffffff;}'
			out=out+'</style></head>'
			out=out+'<body>'
			if (fetch_congestion_res is not None):
				out = out + self.returnsrFetchCongestionResInHtmlTable(fetch_congestion_res)
			if (hybdrid_optimizer_res is not None):
				out = out + self.returnHybdridOptimizerResInHtmlTable(hybdrid_optimizer_res)
			self.log.info("Error Msg ",str(err))
			self.log.info("Type of Error Msg ",type(err))
			if(err is not None):
				out = out + '<h4>Error: Wae was unable to remove congestion from Network due to following error - {}, please fix it! so closed loop can run to remove the Network Congestion.</h4>'.format(str(err))

			emailContent = out + '</body></html>'
			# Email properties
			emailReceiverDic=self.invokeUOPRestApi('/optimization/get_lsp_email','GET','')
			emailReceiver = emailReceiverDic['data'][0]['lsp_email'][0:]
			emailSubject = self.config.get('EmailSettings', 'Subject')
			emailHeader = self.config.get('EmailSettings', 'Header') + " <B>" + datetime.now().strftime(
				"%Y-%m-%d %H:%M") + "</B><BR>"
			emailFooter = self.config.get('EmailSettings', 'Footer') + "<BR>"
			self.log.info("Email content:", emailContent)
			self.log.info("Sending Email notificaiton to ", emailReceiver)
			emailContent = emailHeader + " <BR>" + emailContent + " <BR><BR>" + emailFooter
			# Invoking Notification API to send email
			payload = "{\"body\": \"" + emailContent + "\", \"mail_to\": [\"" + emailReceiver + "\"], \"subject\": \"" + emailSubject + "\"}"
			response = self.invokeUOPRestApi('lsp/notification', "POST", payload)
		except(Exception) as err:
			self.log.error(err)
			pass


	def returnsrFetchCongestionResInHtmlTable(self, srFetchCongestionResponse):
		self.log.info("Invoking returnsrFetchCongestionResInHtmlTable(self, srFetchCongestionResponse)...")
		self.log.info("This method returns fetch congestion response in HTML table format")
		out = ""
		out = '<h1>Before Optimization</h1>'
		try:
			self.log.info("Invoking returnInterfaceListResInHtmlTable()...")
			self.log.info("This method returns interface list in HTML table format")
			out = out + self.returnInterfaceListResInHtmlTable(
				srFetchCongestionResponse['sr-fetch-congestion:output']['congested-interfaces'])
		except(Exception)as err:
			self.log.error("Error@This method returns fetch congestion response in HTML table format,congested-interfaces not found ",err)
			pass
		try:
			self.log.info("Invoking returnLspInHtmlTable()...")
			self.log.info("This method returns SLA violated LSPs list in HTML table format")
			out = out + self.returnLspInHtmlTable(
				srFetchCongestionResponse['sr-fetch-congestion:output']['sla-violated-lsps'], 'sla-violated')
		except(Exception)as err:
			self.log.error("Error@This method returns fetch congestion response in HTML table format,sla-violated LSPs not found ",err)
			pass
		try:
			self.log.info("Invoking  returnLspInHtmlTable()...")
			self.log.info("This method returns congested LSPs list in html table format")
			out = out + self.returnLspInHtmlTable(
				srFetchCongestionResponse['sr-fetch-congestion:output']['congested-lsps'], 'congested')
		except(Exception)as err:
			self.log.error("Error@This method returns fetch congestion response in HTML table format,congested LSPs not found ",err)
			pass


		return out

	def returnInterfaceListResInHtmlTable(self, interfaceList):
		self.log.debug("This method returns interface list in HTML table format")		
		try:
			out = ""
			out = out + '<TABLE class=gridtable>'
			out = out + '<TR><TD colspan=6><h4>Congested Interfaces</h4></TD></TR>'
			out = out + '<TR>'
			out = out + '<TH>Node Name</TH>'
			out = out + '<TH>Dest Node Name</TH>'
			out = out + '<TH>Interface Name </TH>'
			out = out + '<TH>Capacity</TH>'
			out = out + '<TH>Traffic</TH>'
			out = out + '<TH>Utilization</TH>'
			out = out + '</TR>'
			for congested_interface in interfaceList:
				out = out + '<TR>'
				try:
					out = out + '<TD>' + congested_interface['intfSrcNode'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns interface list in HTML table format,intfSrcNode not found ",err)
					out=out+'<TD></TD>'
					pass
				try:
					out = out + '<TD>' + congested_interface['intfDestNode'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns interface list in HTML table format,intfDestNode not found ",err)
					out=out+'<TD></TD>'
					pass
				try:
					out = out + '<TD>' + congested_interface['intfName'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns interface list in HTML table format,intfName not found ",err)
					out=out+'<TD></TD>'
					pass				
				try:
					out = out + '<TD>' + congested_interface['capacity'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns interface list in HTML table format,capacity not found  ",err)
					out=out+'<TD></TD>'
					pass				
				try:
					out = out + '<TD>' + congested_interface['traffic'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns interface list in HTML table format,traffic not found ",err)
					out=out+'<TD></TD>'
					pass				
				try:
					out = out + '<TD>' + congested_interface['utilization'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns interface list in HTML table format,utilization not found ",err)
					out=out+'<TD></TD>'
					pass
				
				out = out + '</TR>'
			out = out + '</TABLE><BR>'
			return out
		except(Exception)as err:
			self.log.error("Error@This method returns interface list in HTML table format,interfaces not found ",err)

	def returnLspPath(self, **argumentsDict):
		self.log.debug("Invoking returnLspPath(self, **argumentsDict)... ")
		self.log.debug("This method create LSP path like node1->node2->destNode")
		try:
			self.log.debug("This block returns congested LSPs list path")
			if (argumentsDict['lspType'] == 'congested'):
				completePathList = argumentsDict['complete_path_list']
				congestedPathList = argumentsDict['congested_path_list']
				destNode = argumentsDict['destNode']
				returnNodePath = ""
				congestedNodeIntfList = []
				self.log.debug("Congested path list ",congestedPathList)
				self.log.debug("Complete path list ",completePathList)


				for congestedPath in congestedPathList:
					congestedNodeIntfList.append(congestedPath['intfSrcNode'].lower().replace(" ","")+':::'+ congestedPath['intfName'].lower().replace(" ",""))

				for completePath in completePathList:
					if (completePath['intfSrcNode'].lower().replace(" ","")+':::'+ completePath['intfName'].lower().replace(" ","")) in congestedNodeIntfList:
						interfaceNameWithPort = self.returnInterfaceNameWithPort(completePath['intfName'])
						returnNodePath = returnNodePath + "<span style=color:red>"+completePath['intfSrcNode']+'('+interfaceNameWithPort+')'+"</span>"+"->"
					else:
						returnNodePath = returnNodePath + completePath['intfSrcNode']+"->"
				returnNodePath=returnNodePath+destNode
				self.log.debug("Return node path for congested LSPs: ",returnNodePath)
				return returnNodePath
		except(Exception)as err:
			self.log.debug("Error@This block returns congested LSPs list path",err)
			pass

		try:
			self.log.debug("This block returns sla violated LSPs list path")
			if (argumentsDict['lspType'] == 'sla_violated'):
				completePathList = argumentsDict['complete_path_list']
				destNode = argumentsDict['destNode']
				returnNodePath = ""
				completeNodePath = ""
				for completePath in completePathList:
					completeNodePath = completeNodePath + completePath['intfSrcNode'] + "->"

				returnNodePath = completeNodePath + destNode
				self.log.debug("Return node path for SLA violated LSPs:",returnNodePath)
				return returnNodePath
		except(Exception)as err:
			self.log.debug("Error@This block returns sla violated LSPs list path",err)
			pass
		
		try:
			self.log.debug("This block returns re-routed LSPs list path")	
			if (argumentsDict['lspType'] == 're_routed'):

				if 'orginial_path_list' in argumentsDict.keys():
					originalPathList = argumentsDict['orginial_path_list']
					destNode = argumentsDict['destNode']
					originalNodePath = ""
					returnNodePath = ""
					for originalPath in originalPathList:
						originalNodePath = originalNodePath + originalPath['intfSrcNode'] + "->"
					returnNodePath = originalNodePath + destNode

				if 'rerouted_path_list' in argumentsDict.keys():
					reRoutedPathList = argumentsDict['rerouted_path_list']
					destNode = argumentsDict['destNode']
					reroutedNodePath = ""
					returnNodePath = ""
					for reroutedPath in reRoutedPathList:
						reroutedNodePath = reroutedNodePath + reroutedPath['intfSrcNode'] + "->"
					returnNodePath = reroutedNodePath + destNode
				self.log.debug("Return node path for re_routed LSPs: ",returnNodePath)
				return returnNodePath
		except(Exception)as err:
			self.log.debug("Error@This block returns re-routed LSPs list path",err)
			pass

		try:
			self.log.debug("This block returns create LSPs list path")	
			if (argumentsDict['lspType'] == 'created'):
				completePathList = argumentsDict['created_path_list']
				destNode = argumentsDict['destNode']
				returnNodePath = ""
				completeNodePath = ""
				for completePath in completePathList:
					completeNodePath = completeNodePath + completePath['intfSrcNode'] + "->"

				returnNodePath = completeNodePath + destNode
				self.log.debug("Return node path for Created LSPs:",returnNodePath)
				return returnNodePath
		except(Exception)as err:
			self.log.debug("Error@This block returns create LSPs list path",err)
			pass

		try:
			self.log.debug("This block returns deleted LSPs list path")	
			if (argumentsDict['lspType'] == 'deleted'):
				completePathList = argumentsDict['deleted_path_list']
				destNode = argumentsDict['destNode']
				returnNodePath = ""
				completeNodePath = ""
				for completePath in completePathList:
					completeNodePath = completeNodePath + completePath['intfSrcNode'] + "->"

				returnNodePath = completeNodePath + destNode
				self.log.debug("Return node path for Deleted LSPs:",returnNodePath)
				return returnNodePath
		except(Exception) as err:
			self.log.error("Error@This block returns deleted LSPs list path",err)
			pass

	def returnLspInHtmlTable(self, lspList, lspType):
		self.log.debug("This method returns LSPs list in HTML table format")
		try:
			if (lspType == 'congested' and len(lspList)>0):
				self.log.debug("This block returns congested LSPs list in html format")
				congested_lsp_list = lspList
				out = ""
				out = out + '<TABLE class=gridtable>'
				out = out + '<TR><TD colspan=8><h4>Congested Lsps</h4></TD></TR>'
				out = out + '<TR>'
				out = out + '<TH>Lsp Name</TH>'
				out = out + '<TH>Lsp Source Node </TH>'
				out = out + '<TH>Lsp Destination Node</TH>'
				out = out + '<TH>Lsp Class</TH>'
				out = out + '<TH>Traffic</TH>'
				out = out + '<TH>Delay</TH>'
				out = out + '<TH>Delay-Sla</TH>'
				out = out + '<TH>Route</TH>'
				out = out + '</TR>'
				for congested_lsp in congested_lsp_list:
					out = out + '<TR>'
					try:
						out = out + '<TD>' + congested_lsp['lspName'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,lspName not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + congested_lsp['lspSrcNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,lspSrcNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + congested_lsp['lspDstNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,lspDstNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspClass(congested_lsp['lspClass']) + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,lspClass not found ",err)
						out=out+'<TD></TD>'
						pass
					try:	
						out = out + '<TD>' + congested_lsp['traffic'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,traffic not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + congested_lsp['delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,delay not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + congested_lsp['delay-sla'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,delay-sla not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspPath(
							congested_path_list=congested_lsp['congested-path']['interfaceKeys'],
							complete_path_list=congested_lsp['complete-path']['interfaceKeys'],
							destNode=congested_lsp['lspDstNode'], lspType="congested") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This method returns LSPs list in HTML table format,contested-path and complete-path not found ",err)
						out=out+'<TD></TD>'
						pass									
					out = out + '</TR>'
				out = out + '</TABLE><BR>'
				return out
		except(Exception) as err:
			self.log.error("Error@This method returns LSPs list in HTML table format,congested LSPs not found ",err)
			
		try:
			if (lspType == 'sla-violated' and len(lspList)>0):
				self.log.info("This block returns sla violated LSPs list in html format")
				sla_violated_lsp_list = lspList
				out = ""
				out = out + '<TABLE class=gridtable>'
				out = out + '<TR><TD colspan=8><h4>SLA Violated Lsps</h4></TD></TR>'
				out = out + '<TR> <TH>Lsp Name</TH>'
				out = out + '<TH>Lsp Source Node </TH>'
				out = out + '<TH>Lsp Destination Node</TH>'
				out = out + '<TH>Lsp Class</TH>'
				out = out + '<TH>Traffic</TH>'
				out = out + '<TH>Delay</TH>'
				out = out + '<TH>Delay-Sla</TH>'
				out = out + '<TH>Route</TH></TR>'
				for sla_violated_lsp in sla_violated_lsp_list:
					out = out + '<TR>'
					try:
						out = out + '<TD>' + sla_violated_lsp['lspName'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,lspName not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + sla_violated_lsp['lspSrcNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,lspSrcNode not found",err)
						out=out+'<TD></TD>'
						pass				
					try:
						out = out + '<TD>' + sla_violated_lsp['lspDstNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,lspDstNode not found",err)
						out=out+'<TD></TD>'
						pass				
					try:
						out = out + '<TD>' + self.returnLspClass(sla_violated_lsp['lspClass']) + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,lspClass not found ",err)
						out=out+'<TD></TD>'
						pass				
					try:
						out = out + '<TD>' + sla_violated_lsp['traffic'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,traffic not found ",err)
						out=out+'<TD></TD>'
						pass				
					try:
						out = out + '<TD>' + sla_violated_lsp['delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,delay not found ",err)
						out=out+'<TD></TD>'
						pass				
					try:
						out = out + '<TD>' + sla_violated_lsp['delay-sla'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,delay-sla not found ",err)
						out=out+'<TD></TD>'
						pass				
					try:
						out = out + '<TD>' + self.returnLspPath(
						complete_path_list=sla_violated_lsp['complete-path']['interfaceKeys'],
						destNode=sla_violated_lsp['lspDstNode'], lspType="sla_violated") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns sla violated LSPs list in html format,complete-path not found ",err)
						out=out+'<TD></TD>'
						pass
					out = out + '</TR>'
				out = out + '</TABLE><BR>'
				return out
		except(Exception)as err:
			self.log.error("Error@This block returns sla violated LSPs list in html format,sla violated LSPs not found ",err)

		try:
			if (lspType == 'rerouted'):
				self.log.info("This block returns rerouted LSPs list in html format")
				re_routed_lsp_list = lspList
				out = ""
				out = out + '<TABLE class=gridtable>'
				out = out + '<TR><TD colspan=9><h4>Re-routed Lsps</h4></TD></TR>'
				out = out + '<TR> <TH>Lsp Name</TH>'
				out = out + '<TH>Lsp Source Node </TH>'
				out = out + '<TH>Lsp Destination Node</TH>'
				out = out + '<TH>Lsp Class</TH>'
				out = out + '<TH>Traffic</TH>'
				out = out + '<TH>Delay</TH>'
				out = out + '<TH>Delay-Sla</TH>'
				out = out + '<TH>Previous Route</TH>'
				out = out + '<TH>New Route</TH>'
				out = out + '</TR>'
				for re_routed_lsp in re_routed_lsp_list:
					out = out + '<TR>'
					try:
						out = out + '<TD>' + re_routed_lsp['lspName'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,lspName not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['lspSrcNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,lspSrcNode not found ",err)
						out=out+'<TD></TD>'
						pass

					try:
						out = out + '<TD>' + re_routed_lsp['lspDstNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,lspDstNode not found ",err)
						out=out+'<TD></TD>'
						pass

					try:
						out = out + '<TD>' + self.returnLspClass(re_routed_lsp['lspClass']) + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,lspClass not found ",err)
						out=out+'<TD></TD>'
						pass

					try:
						out = out + '<TD>' + re_routed_lsp['traffic'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,traffic not found ",err)
						out=out+'<TD></TD>'
						pass

					try:
						out = out + '<TD>' + re_routed_lsp['delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,delay not found ",err)
						out=out+'<TD></TD>'
						pass

					try:
						out = out + '<TD>' + re_routed_lsp['delay-sla'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,delay-sla not found ",err)
						out=out+'<TD></TD>'
						pass

					try:
						out = out + '<TD>' + self.returnLspPath(orginial_path_list=re_routed_lsp['original-path']['hop'],
															destNode=re_routed_lsp['lspDstNode'],
															lspType="re_routed") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,original-path not found ",err)
						out=out+'<TD></TD>'
						pass

					try:
						out = out + '<TD>' + self.returnLspPath(
						rerouted_path_list=re_routed_lsp['re-routed-opt-path']['hop'],
						destNode=re_routed_lsp['lspDstNode'], lspType="re_routed") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns rerouted LSPs list in html format,re-routed-opt-path not found ",err)
						out=out+'<TD></TD>'
						pass

					out = out + '</TR>'
				out = out + '</TABLE><BR>'
				return out
		except(Exception)as err:
			self.log.error("Error@This block returns rerouted LSPs list in html format,re-routed LSPs not found ",err)

		try:
			if (lspType == 'delay-rerouted'):
				self.log.debug("This block returns delay-rerouted LSPs list in html format")
				re_routed_lsp_list = lspList
				out = ""
				out = out + '<TABLE class=gridtable>'
				out = out + '<TR><TD colspan=11><h4>Re-routed Lsps</h4></TD></TR>'
				out = out + '<TR> <TH>Lsp Name</TH>'
				out = out + '<TH>Lsp Source Node </TH>'
				out = out + '<TH>Lsp Destination Node</TH>'
				out = out + '<TH>Lsp Class</TH>'
				out = out + '<TH>Traffic</TH>'
				out = out + '<TH>Delay</TH>'
				out = out + '<TH>Delay-Sla</TH>'
				out = out + '<TH>Previous Delay</TH>'
				out = out + '<TH>New Delay</TH>'
				out = out + '<TH>Original-path</TH>'
				out = out + '<TH>Re-Routed Path</TH>'
				out = out + '</TR>'
				for re_routed_lsp in re_routed_lsp_list:
					out = out + '<TR>'
					try:
						out = out + '<TD>' + re_routed_lsp['lspName'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,lspName not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['lspSrcNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,lspSrcNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['lspDstNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,lspDstNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspClass(re_routed_lsp['lspClass']) + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,lspClass not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['traffic'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,traffic not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,delay not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['delay-sla'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,delay-sla not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['prev-delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,prev-delay not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + re_routed_lsp['delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,delay not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspPath(orginial_path_list=re_routed_lsp['original-path']['hop'],
															destNode=re_routed_lsp['lspDstNode'],
															lspType="re_routed") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,original-path not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspPath(
							rerouted_path_list=re_routed_lsp['re-routed-opt-path']['hop'],
							destNode=re_routed_lsp['lspDstNode'], lspType="re_routed") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns delay-rerouted LSPs list in html format,re-routed-opt-path not found ",err)
						out=out+'<TD></TD>'
						pass

					out = out + '</TR>'
				out = out + '</TABLE><BR>'
				return out
		except(Exception)as err:
			self.log.error("Error@This block returns delay-rerouted LSPs list in html format,delay re-routed LSPs not found ",err)

		try:
			if (lspType == 'created'):
				self.log.debug("This block returns created LSPs list in html format")
				created_lsp_list = lspList
				out = ""
				out = out + '<TABLE class=gridtable>'
				out = out + '<TR><TD colspan=8><h4>Created Lsps</h4></TD></TR>'
				out = out + '<TR>'
				out = out + '<TH>Lsp Name</TH>'
				out = out + '<TH>Lsp Source Node </TH>'
				out = out + '<TH>Lsp Destination Node</TH>'
				out = out + '<TH>Lsp Class</TH>'
				out = out + '<TH>Traffic</TH>'
				out = out + '<TH>Delay</TH>'
				out = out + '<TH>Delay-Sla</TH>'
				out = out + '<TH>Route</TH>'
				out = out + '</TR>'
				for created_lsp in created_lsp_list:
					out = out + '<TR>'
					try:
						out = out + '<TD>' + created_lsp['lspName'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,lspName not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + created_lsp['lspSrcNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,lspSrcNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + created_lsp['lspDstNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,lspDstNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspClass(created_lsp['lspClass']) + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,lspClass not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + created_lsp['traffic'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,traffic not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + created_lsp['delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,delay not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + created_lsp['delay-sla'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,delay-sla not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspPath(
						created_path_list=created_lsp['newly-created-lsp-path']['hop'],
						destNode=created_lsp['lspDstNode'], lspType="created") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns created LSPs list in html format,newly-created-lsp-path not found ",err)
						out=out+'<TD></TD>'
						pass

					out = out + '</TR>'
				out = out + '</TABLE><BR>'
				return out
		except(Exception)as err:
			self.log.error("Error@This block returns created LSPs list in html format,newly-created LSPs not found ",err)
		
		try:
			if (lspType == 'deleted'):
				self.log.debug("This block returns deleted LSPs list in html format")
				deleted_lsp_list = lspList
				out = ""
				out = out + '<TABLE class=gridtable>'
				out = out + '<TR><TD colspan=8><h4>Deleted Lsps</h4></TD></TR>'
				out = out + '<TR>'
				out = out + '<TH>Lsp Name</TH>'
				out = out + '<TH>Lsp Source Node </TH>'
				out = out + '<TH>Lsp Destination Node</TH>'
				out = out + '<TH>Lsp Class</TH>'
				out = out + '<TH>Traffic</TH>'
				out = out + '<TH>Delay</TH>'
				out = out + '<TH>Delay-Sla</TH>'
				out = out + '<TH>Route</TH>'
				out = out + '</TR>'
				for deleted_lsp in deleted_lsp_list:
					out = out + '<TR>'
					try:
						out = out + '<TD>' + deleted_lsp['lspName'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,lspName not found ",err)
						out=out+'<TD></TD>'
						pass					
					try:
						out = out + '<TD>' + deleted_lsp['lspSrcNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,lspSrcNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + deleted_lsp['lspDstNode'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,lspDstNode not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspClass(deleted_lsp['lspClass']) + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,lspClass not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + deleted_lsp['traffic'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,traffic not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + deleted_lsp['prev-delay'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,prev-delay not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + deleted_lsp['delay-sla'] + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,delay-sla not found ",err)
						out=out+'<TD></TD>'
						pass
					try:
						out = out + '<TD>' + self.returnLspPath(
						deleted_path_list=deleted_lsp['deleted-lsp-path']['hop'],
						destNode=deleted_lsp['lspDstNode'], lspType="deleted") + '</TD>'
					except(Exception)as err:
						self.log.error("Error@This block returns deleted LSPs list in html format,deleted-lsp-path not found ",err)
						out=out+'<TD></TD>'
						pass

					out = out + '</TR>'
				out = out + '</TABLE><BR>'
				return out
		except(Exception)as err:
			self.log.error("Error@This block returns deleted LSPs list in html format,deleted LSPs not found ",err)

	def returnHybdridOptimizerResInHtmlTable(self, hybridOptimizerResponse):
		self.log.info("This method returns Hybdrid Optimizer response in HTML table format")
		out = ""
		out = out + '<hr><h1>After Optimization</h1>'
		hybdridOptimizerOut = hybridOptimizerResponse['hybrid-optimizer:output']
		try:
			if(hybdridOptimizerOut['delay-optimization-results']):
				out = out + '<h3>Delay-Optimization-Results</h3>'

				out = out + '<TABLE class=gridtable>'
				out = out + '<TR>'
				out = out + '<TH></TH>'
				out = out + '<TH>Before</TH>'
				out = out + '<TH>After</TH>'
				out = out + '</TR>'

				out = out + '<TR>'
				out = out + '<TD>Number of delay SLA violated VIP LSPs</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['delay-optimization-results']['num-of-delay-sla-violated-vip-lsps-bfr'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,num-of-delay-sla-violated-vip-lsps-bfr not found ",err)
					out=out+'<TD></TD>'
					pass
				try:
					out = out + '<TD>' + hybdridOptimizerOut['delay-optimization-results']['num-of-delay-sla-violated-vip-lsps-aft'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format ,num-of-delay-sla-violated-vip-lsps-aft ",err)
					out=out+'<TD></TD>'
					pass
				out = out + '</TR>'
				out = out + '<TR>'
				out = out + '<TD>Number of delay SLA violated non-VIP LSPs</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['delay-optimization-results'][
						'num-of-delay-sla-violated-non-vip-lsps-bfr'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,num-of-delay-sla-violated-non-vip-lsps-bfr ",err)
					out=out+'<TD></TD>'					
					pass
				
				try:
					out = out + '<TD>' + hybdridOptimizerOut['delay-optimization-results']['num-of-delay-sla-violated-non-vip-lsps-aft'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,num-of-delay-sla-violated-non-vip-lsps-aft ",err)
					out=out+'<TD></TD>'					
					pass
				
				out = out + '</TR>'
				out = out + '<TR>'
				out = out + '<TD>Number of delay re-routed  VIP LSPs</TD>'
				out = out + '<TD>N/A</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['delay-optimization-results']['num-of-delay-rerouted-vip-lsps'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,num-of-delay-rerouted-vip-lsps ",err)
					out=out+'<TD></TD>'					
					pass
				
				
				out = out + '</TR>'
				out = out + '<TR>'
				out = out + '<TD>Number of delay-rerouted-non-vip LSPs</TD>'
				out = out + '<TD>N/A</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['delay-optimization-results']['num-of-delay-rerouted-non-vip-lsps'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,num-of-delay-rerouted-non-vip-lsps ",err)
					out=out+'<TD></TD>'					
					pass
				
				out = out + '</TR>'
				out = out + '</TABLE><BR>'
				try:
					out = out + self.returnLspInHtmlTable(
						hybdridOptimizerOut['delay-optimization-results']['delay-sla-violated-lsps'], 'sla-violated')
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,sla-violated LSPs not found",err)
					out=out+'<TD></TD>'					
					pass
				try:
					out = out + self.returnLspInHtmlTable(
						hybdridOptimizerOut['delay-optimization-results']['delay-re-routed-lsps'], 'delay-rerouted')
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,delay-rerouted LSPs not found ",err)
					out=out+'<TD></TD>'					
					pass
		except(Exception)as err:
			self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, delay optimization result not found ",err)
		
		try:
			if(hybdridOptimizerOut['bandwidth-optimization-results']):
				out = out + '<h3>Bandwidth-Optimization-Results</h3>'

				out = out + '<TABLE class=gridtable>'
				out = out + '<TR>'
				out = out + '<TD>Number of congested interfaces before optimization</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['bandwidth-optimization-results'][
					'num-congested-interfaces-bfr-optimization'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, not found ",err)
					out=out+'<TD></TD>'
					pass
				out = out + '<TD>Number of congested interfaces after optimization</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['bandwidth-optimization-results'][
					'num-congested-interfaces-aft-optimization'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, not found ",err)
					out=out+'<TD></TD>'
					pass
				out = out + '</TR>'
				out = out + '<TR>'
				out = out + '<TD>Maximum interface utilization before optimization</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['bandwidth-optimization-results'][
					'max-intf-utilization-bfr-optimization'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, not found ",err)
					out=out+'<TD></TD>'
					pass				
				out = out + '<TD>Maximum interface utilization after optimization</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['bandwidth-optimization-results'][
					'max-intf-utilization-aft-optimization'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, not found ",err)
					out=out+'<TD></TD>'
					pass				
				out = out + '</TR>'
				out = out + '<TR>'
				out = out + '<TD>Number of re-routed LSPs</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['bandwidth-optimization-results']['num-of-re-routed-lsps'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, not found ",err)
					out=out+'<TD></TD>'
					pass
				out = out + '<TD>Number of created LSPs</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['bandwidth-optimization-results']['num-of-created-lsps'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, not found ",err)
					out=out+'<TD></TD>'
					pass
				out = out + '</TR>'
				out = out + '<TR>'
				out = out + '<TD>Number of deleted LSPs</TD>'
				try:
					out = out + '<TD>' + hybdridOptimizerOut['bandwidth-optimization-results']['num-of-deleted-lsps'] + '</TD>'
				except(Exception)as err:
					self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, not found ",err)
					out=out+'<TD></TD>'
					pass
				out = out + '</TR>'
				out = out + '</TABLE><BR>'
		except(Exception)as err:
			self.log.error("Error@Bandwidth-Optimization-Results ",err)
			pass

		try:
			out = out + self.returnInterfaceListResInHtmlTable(
				hybdridOptimizerOut['bandwidth-optimization-results']['congested-interfaces'])
		except(Exception)as err:
			self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,contested interfaces not found ",err)
			pass
		try:
			out = out + self.returnLspInHtmlTable(
				hybdridOptimizerOut['bandwidth-optimization-results']['congested-lsps'], 'congested')
		except(Exception)as err:
			self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,congested LSPs not found ",err)
			pass
		try:
			out = out + self.returnLspInHtmlTable(
				hybdridOptimizerOut['bandwidth-optimization-results']['re-routed-lsps'], 'rerouted')
		except(Exception)as err:
			self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,re-routed LSPs not found ",err)
			pass	

		try:
			out = out + self.returnLspInHtmlTable(
				hybdridOptimizerOut['bandwidth-optimization-results']['newly-created-lsps'], 'created')
		except(Exception)as err:
			self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format,created LSPs not found ",err)
			pass

		try:
			out = out + self.returnLspInHtmlTable(
				hybdridOptimizerOut['bandwidth-optimization-results']['deleted-lsps'], 'deleted')
		except(Exception)as err:
			self.log.error("Error@This method returns Hybdrid Optimizer response in HTML table format, deleted LSPs not found ",err)
			pass
		return out		

	def returnInterfaceNameWithPort(self,interfaceName):
		try:
			self.log.info("This method returns interface name with port")
			firstLetter=interfaceName[0]
			findAllNumbers=re.findall('\d+',interfaceName)
			returnInterFaceNameWithPortNumber=""
			for num in 	findAllNumbers:
				returnInterFaceNameWithPortNumber=returnInterFaceNameWithPortNumber+"/"+num
			self.log.debug("Returned interface name with port: ",firstLetter+returnInterFaceNameWithPortNumber)
			return firstLetter+returnInterFaceNameWithPortNumber
		except(Exception)as err:
			self.log.debug("Error@This method returns interface name with port",err)
			pass

	def returnLspClass(self,lspClassName):
		try:
			self.log.info("Invoking returnLspClass(self,lspClassName)")
			self.log.info("This method returns LSP class name")
			if(lspClassName=="1"):
				return "VIP Class-I"
			else:
				return "None"			
		except(Exception)as err:
			self.log.info("Error@This method returns LSP class name",err)
			pass


	def prepareYangToJsonForManualEmailNotification(self,input,output):        

		finalPayload={}
		delayBandwidthDict={}
		delayOptimizationResultDict={}
		bandwidthOptimizationResultDict={}
		try:
			if output.delay_optimization_results:
				delayOptimizationResultDict=self.parseDelayOptimizationResult(output.delay_optimization_results)
				delayBandwidthDict['delay-optimization-results']=delayOptimizationResultDict
				self.log.debug("Delay optimization result ",delayOptimizationResultDict)
		except(Exception) as err:
			self.log.error("Delay optimization result is None ",err) 
			pass
		try:
			if output.bandwidth_optimization_results:
				bandwidthOptimizationResultDict=self.parseBandwidthOptimizationResult(output.bandwidth_optimization_results)
				delayBandwidthDict['bandwidth-optimization-results']=bandwidthOptimizationResultDict
				self.log.debug("Bandwidth optimization result ",bandwidthOptimizationResultDict)
		except(Exception)as err:
			self.log.error("Bandwidth optimization result is None ",err)
			pass
		if(len(delayOptimizationResultDict)==0 and len(bandwidthOptimizationResultDict)==0):
			return None
		else:
			finalPayload['hybrid-optimizer:output']=delayBandwidthDict
			self.log.debug("Final payload for email notification API ", json.dumps(finalPayload))
			return finalPayload

	def parseDelayOptimizationResult(self,delayOptimizationResult):
		self.log.info("This method parse delay optimization result in json")
		delayOptimizationResultDict={}
		try:
			delayOptimizationResultDict['num-of-delay-sla-violated-vip-lsps-bfr']=delayOptimizationResult.num_of_delay_sla_violated_vip_lsps_bfr
		except(Exception)as err:
			self.log.error("num-of-delay-sla-violated-vip-lsps-bfr not found ",err)
			pass
		try:
			delayOptimizationResultDict['num-of-delay-sla-violated-non-vip-lsps-bfr']=delayOptimizationResult.num_of_delay_sla_violated_non_vip_lsps_bfr
		except(Exception)as err:
			self.log.error("Error@This method parse delay optimization result in json,num-of-delay-sla-violated-non-vip-lsps-bfr not found ",err)
			pass

		try:
			delayOptimizationResultDict['num-of-delay-sla-violated-vip-lsps-aft']=delayOptimizationResult.num_of_delay_sla_violated_vip_lsps_aft
		except(Exception)as err:
			self.log.error("Error@This method parse delay optimization result in json,num-of-delay-sla-violated-vip-lsps-aft not found ",err)
			pass

		try:
			delayOptimizationResultDict['num-of-delay-sla-violated-non-vip-lsps-bfr']=delayOptimizationResult.num_of_delay_sla_violated_non_vip_lsps_bfr
		except(Exception)as err:
			self.log.error("Error@This method parse delay optimization result in json,num-of-delay-sla-violated-non-vip-lsps-bfr not found ",err)
			pass

		try:
			delayOptimizationResultDict['num-of-delay-rerouted-vip-lsps']=delayOptimizationResult.num_of_delay_rerouted_vip_lsps
		except(Exception)as err:
			self.log.error("Error@This method parse delay optimization result in json,num-of-delay-rerouted-vip-lsps not found ",err)
			pass

		try:
			delayOptimizationResultDict['num-of-delay-rerouted-non-vip-lsps']=delayOptimizationResult.num_of_delay_rerouted_non_vip_lsps
		except(Exception)as err:
			self.log.error("Error@This method parse delay optimization result in json,num-of-delay-rerouted-non-vip-lsps not found ",err)
			pass
		

		try:
			delayReRoutedLsps=delayOptimizationResult.delay_re_routed_lsps
			delayReRoutedLspsList=self.parseLSPYangToJson(delayReRoutedLsps=delayReRoutedLsps,lspType="delay_re_routed_lsps")
			if len(delayReRoutedLspsList)>0:
				delayOptimizationResultDict['delay-re-routed-lsps']=delayReRoutedLspsList
		except(Exception)as err:
			self.log.error("Error@This method parse delay optimization result in json,Delay re-routed LSPs not found ",err)
			pass


		try:
			delaySLAViolatedLsps=delayOptimizationResult.delay_sla_violated_lsps
			delaySLAVioaltedLspsList=self.parseLSPYangToJson(delaySLAViolatedLsps=delaySLAViolatedLsps,lspType="delay_sla_violated_lsps")
			if len(delaySLAVioaltedLspsList)>0:
				delayOptimizationResultDict['delay-sla-violated-lsps']=delaySLAVioaltedLspsList
		except(Exception)as err:
			self.log.error("Error@This method parse delay optimization result in json,Delay LSPs not found ",err)
			pass
		
		self.log.debug("delayOptimizationResultDict ",delayOptimizationResultDict)		
		return delayOptimizationResultDict


	def parseBandwidthOptimizationResult(self,bandwidthOptimizationResult):
		self.log.info("This method parse bandwidth optimization result in json")
		bandwidthOptimizationResultDict={}
		try:
			bandwidthOptimizationResultDict['num-congested-interfaces-bfr-optimization']=bandwidthOptimizationResult.num_congested_interfaces_bfr_optimization
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,num-congested-interfaces-bfr-optimization not found  ",err)
			pass
		try:
			bandwidthOptimizationResultDict['num-congested-interfaces-aft-optimization']=bandwidthOptimizationResult.num_congested_interfaces_aft_optimization
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json, 'num-congested-interfaces-aft-optimization not found ",err)
			pass

		try:	
			bandwidthOptimizationResultDict['max-intf-utilization-bfr-optimization']=bandwidthOptimizationResult.max_intf_utilization_bfr_optimization
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,max-intf-utilization-bfr-optimization not found ",err)
			pass

		try:
			bandwidthOptimizationResultDict['max-intf-utilization-aft-optimization']=bandwidthOptimizationResult.max_intf_utilization_aft_optimization
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,max-intf-utilization-aft-optimization not found ",err)
			pass

		try:
			bandwidthOptimizationResultDict['num-of-re-routed-lsps']=bandwidthOptimizationResult.num_of_re_routed_lsps
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,num-of-re-routed-lsps not found ",err)
			pass

		try:
			bandwidthOptimizationResultDict['num-of-created-lsps']=bandwidthOptimizationResult.num_of_created_lsps
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,num-of-created-lsps not found ",err)
			pass

		try:
			bandwidthOptimizationResultDict['num-of-deleted-lsps']=bandwidthOptimizationResult.num_of_deleted_lsps
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,num-of-deleted-lsps not found ",err)
			pass

		try:
			bandwidthOptimizationCongestedLspList=bandwidthOptimizationResult.congested_lsps
			bandwidthCongestedLspList=self.parseLSPYangToJson(bandwidthContestedLsps=bandwidthOptimizationCongestedLspList,lspType="congested_lsps")
			if len(bandwidthCongestedLspList)>0:
				bandwidthOptimizationResultDict['congested-lsps']=bandwidthCongestedLspList       
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,congested LSPs not found ",err)
			pass
		
		try:
			bandwidthOptimizationCongestedInterfacesList= bandwidthOptimizationResult.congested_interfaces		
			bandwidthCongestedInterfacesList=self.parseBandwidthCongestedInterfaces(bandwidthOptimizationCongestedInterfacesList)
			if len(bandwidthCongestedInterfacesList)>0:
				bandwidthOptimizationResultDict['congested-interfaces']=bandwidthCongestedInterfacesList
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json, contested interfaces not found ",err)
			pass

		try:
			bandwidthOptimizationNewlyCreatedList= bandwidthOptimizationResult.newly_created_lsps		
			bandwidthCongestedNewlyCreatedLspList=self.parseLSPYangToJson(bandwidthNewlyCreatedLsps=bandwidthOptimizationNewlyCreatedList,lspType="newly_created_lsps")
			if len(bandwidthCongestedNewlyCreatedLspList)>0:
				bandwidthOptimizationResultDict['newly-created-lsps']=bandwidthCongestedNewlyCreatedLspList
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json, newly created LSPs not found ",err)
			pass

		try:		
			bandwidthOptimizationDeletedLspList= bandwidthOptimizationResult.deleted_lsps
			bandwidthCongestedDeletedList=self.parseLSPYangToJson(bandwidthDeletedLsps=bandwidthOptimizationDeletedLspList,lspType="deleted_lsps")
			if len(bandwidthCongestedDeletedList)>0: 
				bandwidthOptimizationResultDict['deleted-lsps']=bandwidthCongestedDeletedList
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,deleted LSPs not found ",err)
			pass

		try:
			bandwidthOptimizationReRoutedLspList= bandwidthOptimizationResult.re_routed_lsps
			bandwidthCongestedReRoutedLspList=self.parseLSPYangToJson(bandwidthReRoutedLsps=bandwidthOptimizationReRoutedLspList,lspType="bandwidth_re_routed_lsps")
			if len(bandwidthCongestedReRoutedLspList)>0: 
				bandwidthOptimizationResultDict['re-routed-lsps']=bandwidthCongestedReRoutedLspList
		except(Exception)as err:
			self.log.error("Error@This method parse bandwidth optimization result in json,bandwidth re-routed LSPs not found ",err)
			pass




		return bandwidthOptimizationResultDict

	def parseLSPYangToJson(self,**kwargs):
		print("This method parse bandwidth congested LSPs in json")
		
		if(kwargs['lspType']=="congested_lsps"):
			bandwidthCongestedLspsList=[]	        
			bandwidthCongestedLsps=kwargs['bandwidthContestedLsps']
			for bandwidthCongestedLsp in bandwidthCongestedLsps:
				bandwidthCongestedLspDataDict={}
				bandwidthCongestedLspCompletePathDict={}       
				bandwidthCongestedLspContestedPathDict={}
				try:
					bandwidthCongestedLspDataDict['lspName']=bandwidthCongestedLsp.lspName
				except(Exception) as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,lspName not found ",err)
					pass
				try:
					bandwidthCongestedLspDataDict['lspSrcNode']=bandwidthCongestedLsp.lspSrcNode
				except(Exception) as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,lspSrcNode not found ",err)
					pass

				try:
					bandwidthCongestedLspDataDict['lspDstNode']=bandwidthCongestedLsp.lspDstNode
				except(Exception) as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,lspDstNode not found ",err)
					pass

				try:
					bandwidthCongestedLspDataDict['lspClass']=bandwidthCongestedLsp.lspClass
				except(Exception) as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,lspClass not found ",err)
					pass

				try:
					bandwidthCongestedLspDataDict['traffic']=bandwidthCongestedLsp.traffic
				except(Exception) as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,traffic not found ",err)
					pass

				try:
					bandwidthCongestedLspDataDict['delay']=bandwidthCongestedLsp.delay
				except(Exception) as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,delay not found ",err)
					pass

				try:
					bandwidthCongestedLspDataDict['delay-sla']=bandwidthCongestedLsp.delay_sla
				except(Exception) as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,delay-sla not found ",err)
					pass
		
				try:
					bandwidthCongestedLspCompletePathList=self.parseLspPath(pathType="complete",completePathList=bandwidthCongestedLsp.complete_path.interfaceKeys)
					bandwidthCongestedLspCompletePathDict['interfaceKeys']=bandwidthCongestedLspCompletePathList        
					bandwidthCongestedLspDataDict['complete-path']=bandwidthCongestedLspCompletePathDict
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,complete path not found ",err)
					pass

				try:
					bandwidthCongestedLspContestedPathList=self.parseLspPath(pathType="congested",congestedPathList=bandwidthCongestedLsp.congested_path.interfaceKeys)    
					bandwidthCongestedLspContestedPathDict['interfaceKeys']=bandwidthCongestedLspContestedPathList   
					bandwidthCongestedLspDataDict['congested-path']=bandwidthCongestedLspContestedPathDict
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth congested LSPs in json,congested path not found ",err)
					pass
				bandwidthCongestedLspsList.append(bandwidthCongestedLspDataDict)

			self.log.debug("bandwidthCongestedLspsList ",bandwidthCongestedLspsList)
			return bandwidthCongestedLspsList
		
		if(kwargs['lspType']=="newly_created_lsps"):
			self.log.info("This method parse newly created lsps in bandwidth")
			bandwidthNewlyCreatedLspsList=[]		
			newlyCreatedLsps=kwargs['bandwidthNewlyCreatedLsps']        
			for newlyCreatedLsp in newlyCreatedLsps:
				bandwidthNewlyCreatedLspDataDict={}
				bandwidthCongestedLspNewlyCreatedPathDict={}
				try:
					bandwidthNewlyCreatedLspDataDict['lspName']=newlyCreatedLsp.lspName
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,lspName not found ",err)
					pass
				try:
					bandwidthNewlyCreatedLspDataDict['lspSrcNode']=newlyCreatedLsp.lspSrcNode
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,lspSrcNode not found ",err)
					pass

				try:
					bandwidthNewlyCreatedLspDataDict['lspDstNode']=newlyCreatedLsp.lspDstNode
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,lspDstNode not found ",err)
					pass

				try:
					bandwidthNewlyCreatedLspDataDict['lspClass']=newlyCreatedLsp.lspClass
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,lspClass not found ",err)
					pass

				try:
					bandwidthNewlyCreatedLspDataDict['traffic']=newlyCreatedLsp.traffic
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,traffic not found ",err)
					pass

				try:
					bandwidthNewlyCreatedLspDataDict['delay']=newlyCreatedLsp.delay
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,delay not found ",err)
					pass

				try:
					bandwidthNewlyCreatedLspDataDict['delay-sla']=newlyCreatedLsp.delay_sla
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,delay-sla not found ",err)
					pass
				try:		
					bandwidthCongestedLspNewPathList=self.parseHopList(hopType="newly_created_lsp",newlyCreatedLspPath=newlyCreatedLsp.newly_created_lsp_path.hop)
					bandwidthCongestedLspNewlyCreatedPathDict['hop']=bandwidthCongestedLspNewPathList
					bandwidthNewlyCreatedLspDataDict['newly-created-lsp-path']=bandwidthCongestedLspNewlyCreatedPathDict
				except(Exception)as err:
					self.log.error("Error@This method parse newly created lsps in bandwidth,newly created LSP path not found ",err)
				bandwidthNewlyCreatedLspsList.append(bandwidthNewlyCreatedLspDataDict)

			return bandwidthNewlyCreatedLspsList
			
		if(kwargs['lspType']=="deleted_lsps"):
			self.log.info("This method parse deleted LSPs")
			bandwidthDeletedLspsList=[]		   
			deletedLsps=kwargs['bandwidthDeletedLsps']     
			for deletedLsp in deletedLsps:
				bandwidthDeletedLspDataDict={}
				bandwidthCongestedDeletedLspPathDict={}
				try:
					bandwidthDeletedLspDataDict['lspName']=deletedLsp.lspName
				except(Exception)as err:
					self.log.error("Error@This method parse deleted LSPs,lspName not found ",err)
					pass
				try:
					bandwidthDeletedLspDataDict['lspSrcNode']=deletedLsp.lspSrcNode
				except(Exception)as err:
					self.log.error("Error@This method parse deleted LSPs,lspSrcNode not found ",err)
					pass
				try:
					bandwidthDeletedLspDataDict['lspDstNode']=deletedLsp.lspDstNode
				except(Exception)as err:
					self.log.error("Error@This method parse deleted LSPs,lspDstNode not found ",err)
					pass
				try:
					bandwidthDeletedLspDataDict['lspClass']=deletedLsp.lspClass
				except(Exception)as err:
					self.log.error("Error@This method parse deleted LSPs,lspClass not found",err)
					pass

				try:
					bandwidthDeletedLspDataDict['traffic']=deletedLsp.traffic
				except(Exception)as err:
					self.log.error("Error@This method parse deleted LSPs,traffic not found ",err)
					pass

				try:
					bandwidthDeletedLspDataDict['prev-delay']=deletedLsp.prev_delay
				except(Exception)as err:
					self.log.error("Error@This method parse deleted LSPs,delay not found ",err)
					pass

				try:
					bandwidthDeletedLspDataDict['delay-sla']=deletedLsp.delay_sla
				except(Exception)as err:
					self.log.error("Error@This method parse deleted LSPs,delay-sla not foun ",err)
					pass
				try:
					bandwidthCongestedDeletedLspPathList=self.parseHopList(hopType="deleted_lsp",deletedLspPath=deletedLsp.deleted_lsp_path.hop)
					bandwidthCongestedDeletedLspPathDict['hop']=bandwidthCongestedDeletedLspPathList
					bandwidthDeletedLspDataDict['deleted-lsp-path']=bandwidthCongestedDeletedLspPathDict
				except(Exception) as err:
					self.log.error("Error@This method parse deleted LSPs,deleted LSPs path not found ",err)
					pass
				bandwidthDeletedLspsList.append(bandwidthDeletedLspDataDict)
			return bandwidthDeletedLspsList
		
		if(kwargs['lspType']=="bandwidth_re_routed_lsps"):
			self.log.info("This method parse bandwidth re-routed LSPs")
			bandwidthReRoutedLspsList=[]	
			reRoutedLsps=kwargs['bandwidthReRoutedLsps']	        
			for reRoutedLsp in reRoutedLsps:
				bandwidthReRoutedLspDataDict={}
				bandwidthReRoutedLpsOriginalPathDict={}       
				bandwidthReRoutedLpsReRoutedPathDict={}
				try:	
					bandwidthReRoutedLspDataDict['lspName']=reRoutedLsp.lspName
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,lspName not found ",err)
					pass
				try:
					bandwidthReRoutedLspDataDict['lspSrcNode']=reRoutedLsp.lspSrcNode
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,lspSrcNode not found ",err)
					pass

				try:
					bandwidthReRoutedLspDataDict['lspDstNode']=reRoutedLsp.lspDstNode
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,lspDstNode not found ",err)
					pass

				try:
					bandwidthReRoutedLspDataDict['lspClass']=reRoutedLsp.lspClass
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,lspClass not found ",err)
					pass

				try:
					bandwidthReRoutedLspDataDict['traffic']=reRoutedLsp.traffic
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,traffic not found ",err)
					pass

				try:
					bandwidthReRoutedLspDataDict['delay']=reRoutedLsp.delay
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,delay not found ",err)
					pass

				try:
					bandwidthReRoutedLspDataDict['delay-sla']=reRoutedLsp.delay_sla
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,delay-sla not found ",err)
					pass
				

				try:
					bandwidthReRoutedLpsOrignalPathList=self.parseHopList(hopType="bandwidthOrignalPath",orignalPathList=reRoutedLsp.original_path.hop)
					bandwidthReRoutedLpsOriginalPathDict['hop']=bandwidthReRoutedLpsOrignalPathList        
					bandwidthReRoutedLspDataDict['original-path']=bandwidthReRoutedLpsOriginalPathDict
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs,bandwidth re-routed LSP orignal path not found ",err)
					pass
				try:
					bandwidthReRoutedLpsPathList=self.parseHopList(hopType="bandwidthReRoutedOptPath",reRoutedPathList=reRoutedLsp.re_routed_opt_path.hop)    
					bandwidthReRoutedLpsReRoutedPathDict['hop']=bandwidthReRoutedLpsPathList   
					bandwidthReRoutedLspDataDict['re-routed-opt-path']=bandwidthReRoutedLpsReRoutedPathDict
				except(Exception)as err:
					self.log.error("Error@This method parse bandwidth re-routed LSPs, bandwidth re-routed LSP path not found ",err)
					pass
			
				bandwidthReRoutedLspsList.append(bandwidthReRoutedLspDataDict)
			self.log.debug("Bandwidth re-routed LSPs list ",bandwidthReRoutedLspsList)
			return bandwidthReRoutedLspsList
		
		if(kwargs['lspType']=="delay_re_routed_lsps"):
			self.log.info("This method parse delay re-routed lsps in json")
			delayReroutedLspsList=[]
			delayReroutedLsps=kwargs['delayReRoutedLsps']
			for delayReroutedLsp in delayReroutedLsps:
				delayReroutedLspDataDict={}
				delayRoutedLpsOriginalPathDict={}       
				delayReRoutedLpsReRoutedPathDict={}
				try:
					delayReroutedLspDataDict['lspName']=delayReroutedLsp.lspName
				except(Exception)as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP Name not found ",err)
					pass
				try:	
					delayReroutedLspDataDict['lspSrcNode']=delayReroutedLsp.lspSrcNode
				except(Exception)as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP Source node not found ",err)			
					pass
				try:
					delayReroutedLspDataDict['lspDstNode']=delayReroutedLsp.lspDstNode
				except(Exception) as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP destination node not found ",err)
					pass
				try:
					delayReroutedLspDataDict['lspClass']=delayReroutedLsp.lspClass
				except(Exception) as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP class not found ",err)
					pass
				try:
					delayReroutedLspDataDict['traffic']=delayReroutedLsp.traffic
				except(Exception) as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP traffic not found ",err)
					pass
				try:
					delayReroutedLspDataDict['delay']=delayReroutedLsp.delay
				except(Exception) as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP delay not found ",err)
					pass
				try:
					delayReroutedLspDataDict['delay-sla']=delayReroutedLsp.delay_sla
				except(Exception) as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP delay-sla not found ",err)
					pass
				try:
					delayReroutedLspDataDict['prev-delay']=delayReroutedLsp.prev_delay
				except(Exception) as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,LSP pre-delay not found ",err)
					pass
				
				try:
					delayReRoutedLpsHopList=self.parseHopList(hopType="delayOrignalPath",orignalPathList=delayReroutedLsp.original_path.hop)
					delayRoutedLpsOriginalPathDict['hop']=delayReRoutedLpsHopList        
					delayReroutedLspDataDict['original-path']=delayRoutedLpsOriginalPathDict
				except(Exception)as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,orignal path hops not found ",err)
					pass

				try:
					delayReRoutedLpsHopList=self.parseHopList(hopType="delayReRoutedOptPath",reRoutedPathList=delayReroutedLsp.re_routed_opt_path.hop)    
					delayReRoutedLpsReRoutedPathDict['hop']=delayReRoutedLpsHopList   
					delayReroutedLspDataDict['re-routed-opt-path']=delayReRoutedLpsReRoutedPathDict
				except(Exception)as err:
					self.log.error("Error@This method parse delay re-routed lsps in json,re routed path hops not found ",err)
					pass

				delayReroutedLspsList.append(delayReroutedLspDataDict)

			self.log.debug("Delay re-routed LSPs List ",delayReroutedLspsList)
			return delayReroutedLspsList


		if(kwargs['lspType']=="delay_sla_violated_lsps"):
			self.log.info("This method parse delay lsps in json")
			delaySLAViolatedLspsList=[]
			delaySLAViolatedLsps=kwargs['delaySLAViolatedLsps']
			for slaviolatedLsp in delaySLAViolatedLsps:
				delaySLAViolatedLspDataDict={}
				delayCompletePathDict={}       
				try:
					delaySLAViolatedLspDataDict['lspName']=slaviolatedLsp.lspName
				except(Exception)as err:
					self.log.error("Error@This method parse delay lsps in json,LSP Name not found ",err)
					pass
				try:	
					delaySLAViolatedLspDataDict['lspSrcNode']=slaviolatedLsp.lspSrcNode
				except(Exception)as err:
					self.log.error("Error@This method parse delay lsps in json,LSP Source node not found ",err)			
					pass
				try:
					delaySLAViolatedLspDataDict['lspDstNode']=slaviolatedLsp.lspDstNode
				except(Exception) as err:
					self.log.error("Error@This method parse delay lsps in json,LSP destination node not found ",err)
					pass
				try:
					delaySLAViolatedLspDataDict['lspClass']=slaviolatedLsp.lspClass
				except(Exception) as err:
					self.log.error("Error@This method parse delay lsps in json,LSP class not found ",err)
					pass
				try:
					delaySLAViolatedLspDataDict['traffic']=slaviolatedLsp.traffic
				except(Exception) as err:
					self.log.error("Error@This method parse delay lsps in json,LSP traffic not found ",err)
					pass
				try:
					delaySLAViolatedLspDataDict['delay']=slaviolatedLsp.delay
				except(Exception) as err:
					self.log.error("Error@This method parse delay lsps in json,LSP delay not found ",err)
					pass
				try:
					delaySLAViolatedLspDataDict['delay-sla']=slaviolatedLsp.delay_sla
				except(Exception) as err:
					self.log.error("Error@This method parse delay lsps in json,LSP delay-sla not found ",err)
					pass
				
				try:
					delayLpsHopList=self.parseLspPath(pathType="delay_complete_path",completePathList=slaviolatedLsp.complete_path.interfaceKeys)
					delayCompletePathDict['interfaceKeys']=delayLpsHopList
					delaySLAViolatedLspDataDict['complete-path']=delayCompletePathDict
				except(Exception)as err:
					self.log.error("Error@This method parse delay lsps in json,orignal path hops not found ",err)
					pass


				delaySLAViolatedLspsList.append(delaySLAViolatedLspDataDict)

			self.log.debug("Delay LSPs List ",delaySLAViolatedLspsList)
			return delaySLAViolatedLspsList


	def parseBandwidthCongestedInterfaces(self,bandwidthCongestedInterfaces):
		self.log.info("This method parse bandwidth congested interfaces")
		bandwidthCongestedInterfacesList=[]			
		for bandwidthCongestedInterface in bandwidthCongestedInterfaces:
			bandwidthCongestedInterfacesDataDict={}
			try:
				bandwidthCongestedInterfacesDataDict['intfSrcNode']=bandwidthCongestedInterface.intfSrcNode
			except(Exception)as  err:
				self.log.error("Error@This method parse bandwidth congested interfaces,intfSrcNode not found ",err)
				pass
			try:
				bandwidthCongestedInterfacesDataDict['intfName']=bandwidthCongestedInterface.intfName
			except(Exception)as  err:
				self.log.error("Error@This method parse bandwidth congested interfaces,intfName not found ",err)
				pass

			try:
				bandwidthCongestedInterfacesDataDict['intfDestNode']=bandwidthCongestedInterface.intfDestNode
			except(Exception)as  err:
				self.log.error("Error@This method parse bandwidth congested interfaces,intfDestNode not found ",err)
				pass

			try:
				bandwidthCongestedInterfacesDataDict['traffic']=bandwidthCongestedInterface.traffic
			except(Exception)as  err:
				self.log.error("Error@This method parse bandwidth congested interfaces,traffic not found ",err)
				pass

			try:
				bandwidthCongestedInterfacesDataDict['utilization']=bandwidthCongestedInterface.utilization
			except(Exception)as  err:
				self.log.error("Error@This method parse bandwidth congested interfaces,utilization not found ",err)
				pass

			try:
				bandwidthCongestedInterfacesDataDict['capacity']=bandwidthCongestedInterface.capacity
			except(Exception)as  err:
				self.log.error("Error@This method parse bandwidth congested interfaces,capacity not found ",err)
				pass

			bandwidthCongestedInterfacesList.append(bandwidthCongestedInterfacesDataDict)		
		self.log.debug("Bandwidth congested Interfaces list ",bandwidthCongestedInterfacesList)
		return bandwidthCongestedInterfacesList


	def parseLspPath(self,**kwargs):
	
		if (kwargs['pathType']=='complete'):
			self.log.info("This block parse complete path of bandwidth congested LSPs")
			completePathList=kwargs['completePathList']
			bandwidthCongLspCompletePathList=[]
			for completePath in completePathList: 
				bandwidthCongLspCompletePathDataDict={}
				try:
					bandwidthCongLspCompletePathDataDict['intfSrcNode']=completePath.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block parse complete path of bandwidth congested LSPs ,intfSrcNode not found ",err)
					pass
				try:
					bandwidthCongLspCompletePathDataDict['intfName']=completePath.intfName
				except(Exception)as err:
					self.log.error("Error@This block parse complete path  of bandwidth congested LSPs,intfName ",err)
					pass

				bandwidthCongLspCompletePathList.append(bandwidthCongLspCompletePathDataDict)
			self.log.debug("bandwidthCongLspCompletePathDataDict ",bandwidthCongLspCompletePathDataDict)
			return bandwidthCongLspCompletePathList
	
		elif(kwargs['pathType']=='congested'):
			self.log.info("This block parse congested path of bandwidth congested LSPs")
			congestedPathList=kwargs['congestedPathList']
			bandwidthCongestedPathList=[]
			for congestedPath in congestedPathList: 
				bandwidthCongestedPathDataDict={}
				try:
					bandwidthCongestedPathDataDict['intfSrcNode']=congestedPath.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block parse congested path of bandwidth congested LSPs,intfSrcNode not found ",err)
					pass
				try:
					bandwidthCongestedPathDataDict['intfName']=congestedPath.intfName
				except(Exception)as err:
					self.log.error("Error@This block parse congested path of bandwidth congested LSPs,intfName not found ",err)
					pass
				bandwidthCongestedPathList.append(bandwidthCongestedPathDataDict)
			self.log.debug("bandwidthCongLspCongestedPathList ",bandwidthCongestedPathList)
			return bandwidthCongestedPathList
		else:
			self.log.debug("Pathtype not found")

		if (kwargs['pathType']=='delay_complete_path'):
			self.log.info("This block parse complete path of delay violated LSPs")
			completePathList=kwargs['completePathList']
			delayViolatedLspCompletePathList=[]
			for completePath in completePathList: 
				delayLspCompletePathDataDict={}
				try:
					delayLspCompletePathDataDict['intfSrcNode']=completePath.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block parse complete path of delay violated LSPs ,intfSrcNode not found ",err)
					pass
				try:
					delayLspCompletePathDataDict['intfName']=completePath.intfName
				except(Exception)as err:
					self.log.error("Error@This block parse complete path  of delay violated LSPs,intfName not found ",err)
					pass

				delayViolatedLspCompletePathList.append(delayLspCompletePathDataDict)
			self.log.debug("delayLspCompletePathDataDict ",delayLspCompletePathDataDict)
			return delayViolatedLspCompletePathList

				

	def parseHopList(self,**kwargs):
		if (kwargs['hopType']=='delayOrignalPath'):
			self.log.info("This block prepare orignal path of delay LSPs ")
			orignalPathList=kwargs['orignalPathList']
			delayReRoutedLspHopList=[]
			for orignalPath in orignalPathList: 
				delayReRoutedLspHopDataDict={}
				try:
					delayReRoutedLspHopDataDict['step']=orignalPath.step
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of delay LSPs,step not found ",err)
					pass
				try:
					delayReRoutedLspHopDataDict['ip-address']=orignalPath.ip_address
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of delay LSPs, ip-address not found ",err)
					pass
				try:
					delayReRoutedLspHopDataDict['intfSrcNode']=orignalPath.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of delay LSPs,intfSrcNode not found ",err)
					pass
				try:
					delayReRoutedLspHopDataDict['intfName']=orignalPath.intfName
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of delay LSPs,intfName not found ",err)
					pass
				
				delayReRoutedLspHopList.append(delayReRoutedLspHopDataDict)

			self.log.debug("Prepared delay LSP orignal path ",delayReRoutedLspHopList)
			return delayReRoutedLspHopList

		elif (kwargs['hopType']=='delayReRoutedOptPath'):
			self.log.info("This block prepare re-routed-opt path of  delay LSPs ")
			reRoutedPathList=kwargs['reRoutedPathList']
			reRoutedLpsHopList=[]
			for reRoutedPath in reRoutedPathList:
				reRoutedLspHopDataDict={}
				try:
					reRoutedLspHopDataDict['step']=reRoutedPath.step
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  delay LSPs ,step not found ",err)
					pass
				try:
					reRoutedLspHopDataDict['ip-address']=reRoutedPath.ip_address
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  delay LSPs ,ip-address not found ",err)
					pass
				try:
					reRoutedLspHopDataDict['intfSrcNode']=reRoutedPath.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  delay LSPs ,intfSrcNode not found ",err)
					pass

				try:
					reRoutedLspHopDataDict['intfName']=reRoutedPath.intfName
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  delay LSPs ,intfName not found ",err)
					pass

				reRoutedLpsHopList.append(reRoutedLspHopDataDict)
			self.log.debug("Prepared delay LSP re-routed opt path ",reRoutedLpsHopList)
			return reRoutedLpsHopList

		elif (kwargs['hopType']=='bandwidthOrignalPath'):
			self.log.info("This block prepare orignal path of bandwidth LSPs ")
			orignalPathList=kwargs['orignalPathList']
			bandwidthReRoutedLspHopList=[]
			for orignalPath in orignalPathList: 
				bandwidthReRoutedLspHopDataDict={}
				try:
					bandwidthReRoutedLspHopDataDict['step']=orignalPath.step
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of bandwidth LSPs,step not found ",err)
					pass
				try:
					bandwidthReRoutedLspHopDataDict['ip-address']=orignalPath.ip_address
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of bandwidth LSPs, ip-address not found ",err)
					pass
				try:
					bandwidthReRoutedLspHopDataDict['intfSrcNode']=orignalPath.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of bandwidth LSPs,intfSrcNode not found ",err)
					pass
				try:
					bandwidthReRoutedLspHopDataDict['intfName']=orignalPath.intfName
				except(Exception)as err:
					self.log.error("Error@This block prepare orignal path of bandwidth LSPs,intfName not found ",err)
					pass
				bandwidthReRoutedLspHopList.append(bandwidthReRoutedLspHopDataDict)

			self.log.debug("Prepared bandwidth LSP orignal path ",bandwidthReRoutedLspHopList)
			return bandwidthReRoutedLspHopList


		elif (kwargs['hopType']=='bandwidthReRoutedOptPath'):
			self.log.info("This block prepare re-routed-opt path of  bandwidth LSPs ")
			reRoutedPathList=kwargs['reRoutedPathList']
			reRoutedLspHopList=[]
			for reRoutedPath in reRoutedPathList:
				reRoutedLpsHopDataDict={}
				try:
					reRoutedLpsHopDataDict['step']=reRoutedPath.step
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  bandwidth LSPs ,step not found ",err)
					pass
				try:
					reRoutedLpsHopDataDict['ip-address']=reRoutedPath.ip_address
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  bandwidth LSPs ,ip-address not found ",err)
					pass
				try:
					reRoutedLpsHopDataDict['intfSrcNode']=reRoutedPath.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  bandwidth LSPs ,intfSrcNode not found ",err)
					pass

				try:
					reRoutedLpsHopDataDict['intfName']=reRoutedPath.intfName
				except(Exception)as err:
					self.log.error("Error@This block prepare re-routed-opt path of  bandwidth LSPs ,intfName not found ",err)
					pass

				reRoutedLspHopList.append(reRoutedLpsHopDataDict)
			self.log.debug("Prepared bandwidth LSP re-routed opt path ",reRoutedLspHopList)
			return reRoutedLspHopList


		elif (kwargs['hopType']=='newly_created_lsp'):
			self.log.info("This block prepare newly created LSP list ")
			newlyCreatedLspPathList=kwargs['newlyCreatedLspPath']
			newlyCreatedLpsHopList=[]
			for newlyCreatedLsp in newlyCreatedLspPathList:
				newlyCreatedLpsHopDataDict={}
				try:
					newlyCreatedLpsHopDataDict['step']=newlyCreatedLsp.step
				except(Exception)as err:
					self.log.error("Error@This block prepare newly created LSP list,step not found ",err)
					pass
				try:
					newlyCreatedLpsHopDataDict['ip-address']=newlyCreatedLsp.ip_address
				except(Exception)as err:
					self.log.error("Error@This block prepare newly created LSP list,ip-address not found ",err)
					pass
				try:
					newlyCreatedLpsHopDataDict['intfSrcNode']=newlyCreatedLsp.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block prepare newly created LSP list intfSrcNode not found ",err)
					pass
				try:
					newlyCreatedLpsHopDataDict['intfName']=newlyCreatedLsp.intfName
				except(Exception)as err:
					self.log.error("Error@This block prepare newly created LSP list intfName not found",err)
					pass

				newlyCreatedLpsHopList.append(newlyCreatedLpsHopDataDict)
			self.log.debug("Prepared newly created LSPs List ",newlyCreatedLpsHopList)
			return newlyCreatedLpsHopList


		elif (kwargs['hopType']=='deleted_lsp'):
			self.log.info("This block prepare deleted LSPs list ")
			deletedLspsPathList=kwargs['deletedLspPath']
			deletedLspHopList=[]
			for deletedLsp in deletedLspsPathList:
				deletedLspHopDataDict={}
				try:
					deletedLspHopDataDict['step']=deletedLsp.step
				except(Exception)as err:
					self.log.error("Error@This block prepare deleted LSPs list,step not found ",err)
					pass
				try:
					deletedLspHopDataDict['ip-address']=deletedLsp.ip_address
				except(Exception)as err:
					self.log.error("Error@This block prepare deleted LSPs list,ip-address not found ",err)
					pass
				
				try:
					deletedLspHopDataDict['intfSrcNode']=deletedLsp.intfSrcNode
				except(Exception)as err:
					self.log.error("Error@This block prepare deleted LSPs list,intfSrcNode not found ",err)
					pass

				try:
					deletedLspHopDataDict['intfName']=deletedLsp.intfName
				except(Exception)as err:
					self.log.error("Error@This block prepare deleted LSPs list,intfName not found ",err)
					pass

				deletedLspHopList.append(deletedLspHopDataDict)
			self.log.debug("Prepared deleted LSPs List ",deletedLspHopList)
			return deletedLspHopList
		else:
			self.log.debug("hopType not found")


	def callFetchCongestion(self, threshold):
		self.log.debug("Invoking FetchCongestion")
		try:
			
			payload = self.generateOpmPayload(payload_type="fetch_congestion_payload",threshold=threshold)		
			#self.log.debug("CloseLoop is fetching congestion")
			self.log.debug("Fetch Congestion Payload: ",payload)
			response = self.invokeWaeOpmRestApi("opm/sr-fetch-congestion/run","POST",payload)
			self.log.debug("Fetch Congestion Response :",response)
			fetch_congestion_res = response
			return fetch_congestion_res
		except(Exception) as err:
			self.log.debug(err)
			pass

	def generateOpmPayload(self, **kwargs):
		self.log.info("Invoking generateOpmPayload ")
		if(kwargs['payload_type']=="bandwidth"):
			self.log.debug("This block generates BW payload")
			## CREATE BW PAYLOAD
			bw_lsp_payload = []
			lsp_to_be_reported=kwargs['congested_lsps_to_be_reported']
			for lsp in lsp_to_be_reported:
				lsp_key = lsp.split(':::')
				lsp_name = lsp_key[0]
				lsp_src =  lsp_key[1]
				lsp_dict = {"lspSrcNode": lsp_src, "lspName" : lsp_name }
				bw_lsp_payload.append(lsp_dict)

			bw_final_payload = bw_lsp_payload
			self.log.debug("bandwidth optimization payload to invoke hybdrid optimizer",bw_final_payload)
			return bw_final_payload

		elif(kwargs['payload_type']=="delay"):	
			## CREATE DELAY PAYLOAD
			self.log.debug("This block generates DELAY payload")
			delay_lsp_payload = []
			lsp_to_be_reported=kwargs['sla_violated_lsps_to_be_reported']
			for lsp in lsp_to_be_reported:
				lsp_key = lsp.split(':::')
				lsp_name = lsp_key[0]
				lsp_src =  lsp_key[1]
				lsp_dict = {"lspSrcNode": lsp_src, "lspName" : lsp_name }
				delay_lsp_payload.append(lsp_dict)

			delay_final_payload = delay_lsp_payload
			self.log.debug("delay  optimization payload to invoke hybrid optimizer",delay_final_payload)
			return delay_final_payload

		elif(kwargs['payload_type']=="fetch_congestion_payload"):
			self.log.debug("This block generates input payload for fetch congestion")
			thresholdValue=kwargs['threshold']
			fetchCongestionFinalPayload={}
			payloadValue={"interface-utilization":thresholdValue}
			fetchCongestionFinalPayload["input"]=payloadValue
			fetchCongestionFinalPayload=json.dumps(fetchCongestionFinalPayload)
			self.log.info("input payload for fetch congestion",fetchCongestionFinalPayload)
			return fetchCongestionFinalPayload

		elif(kwargs['payload_type']=="hybrid_optimizer_payload"):
			self.log.debug("This block generates input payload for hybrid optimizer")
			thresholdValue=kwargs['threshold']
			congested_lsps_list=kwargs['congested_lsps_list_payload']
			sla_violated_lsps_list=kwargs['sla_violated_lsps_list_payload']
			create_lsp=kwargs['create_lsp']
			hybridoptimizerFinalPayload={}
			if(create_lsp==True):
				payloadValue={"post-optimization-threshold":thresholdValue,
				"action-type":"force-commit",
				"lsps-to-be-optimized":congested_lsps_list,
				"exclude-vip-tunnels":"true",
				"create-new-lsps":"true",
				"delay-lsps-to-be-optimized":sla_violated_lsps_list}
				hybridoptimizerFinalPayload["input"]=payloadValue
				self.log.info("input payload for hybrid optimizer when create LSPs flag is true")
				return json.dumps(hybridoptimizerFinalPayload)
			else:
				payloadValue={"post-optimization-threshold":thresholdValue,
				"action-type":"force-commit",
				"lsps-to-be-optimized":congested_lsps_list,
				"exclude-vip-tunnels":"true",
				"create-new-lsps":"false",
				"delay-lsps-to-be-optimized":sla_violated_lsps_list}
				hybridoptimizerFinalPayload["input"]=payloadValue
				self.log.info("input payload for hybrid optimizer when create LSPs flag is false")
				return json.dumps(hybridoptimizerFinalPayload)


		else:
			return None

	def invokeEXFOServerRestApi(self,**kwargs):
		self.log.debug("Fetching server details from properties file ")
		exfoServerIp =  self.config.get("EXFOServer","ExfoTwampServerIp")
		url=kwargs['url']
		onDemandTwampHeadersPayload=kwargs['onDemandTwampHeadersPayload']
		onDemandTwampBodyPayload=kwargs['onDemandTwampBodyPayload']

		if "Login"  in url:
			url = "https://"+exfoServerIp+"/API/REST/"+url
			self.log.debug("URL for EXFO TWAMP Login API ",url)

		if "OnDemand/v1/Run" in url and kwargs['requestType']=="POST_RUN":
			url = "https://"+exfoServerIp+"/API/REST/"+url
			self.log.debug("URL for EXFO TWAMP run API ",url)

		if "OnDemand/v1/Run" in url and kwargs['requestType']=="GET_RESULT":
			url = "https://"+exfoServerIp+"/API/REST/"+url
			self.log.debug("URL for EXFO TWAMP get result API ",url)

		if "Logoff/HTTP/1.1" in url:
			url = "https://"+exfoServerIp+"/API/REST/"+url
			self.log.debug("URL for EXFO TWAMP Logoff API ",url)


		if kwargs['requestType']== "POST_LOGIN":           
			self.log.debug("Invoking EXFO TWAMP Login API with url{} headerPayload{} and bodyPayload{}".format(url,onDemandTwampHeadersPayload,onDemandTwampBodyPayload))
			response = requests.request("POST", url, headers=onDemandTwampHeadersPayload,data=onDemandTwampBodyPayload,verify=False)
			self.log.debug("Response from Login API ",dict(response.cookies))
			return dict(response.cookies)

		elif kwargs['requestType']=="POST_RUN":
			onDemandTwampBodyPayload=json.dumps(onDemandTwampBodyPayload)
			self.log.debug("Invoking EXFO TWAMP run API with url{} and bodyPayload{}".format(url,onDemandTwampBodyPayload))
			response = requests.request("POST", url, headers=onDemandTwampHeadersPayload,data=onDemandTwampBodyPayload,verify=False)
			self.log.debug("Response from EXFO TWAMP run API ",response.text)
			return response.text
						
		elif kwargs['requestType']=='GET_RESULT':            
			self.log.debug("Invoking EXFO TWAMP get result API with url{} and headersPayload{}".format(url,onDemandTwampHeadersPayload))
			response = requests.request("GET", url,headers=onDemandTwampHeadersPayload,verify=False)
			self.log.debug("Response from EXFO TWAMP get result API ",response.text)            
			return response.text

		elif kwargs['requestType']=='GET_LOGOFF':            
			self.log.debug("Invoking EXFO TWAMP get result API with url{} and headersPayload{}".format(url,onDemandTwampHeadersPayload))
			response = requests.request("GET", url,headers=onDemandTwampHeadersPayload,verify=False)
			self.log.debug("Response from EXFO TWAMP get result API ",response)            
			return response
	
	def generatePayloadForExfo(self,**kwargs):
		restApiUserName = self.config.get("EXFOServer","ExfoTwampUserName")
		restApiPassword = self.config.get("EXFOServer","ExfoTwampUserPass")

		if kwargs['requestType'] == "GET_LOGIN":
			onDemandTwampLoginHeadersPayload={}
			onDemandTwampLoginBodyPayload="uname="+restApiUserName+"&pword="+restApiPassword+"&format=json"
			self.log.debug("Creating header payload for EXFO TWAMP Login API")
			onDemandTwampLoginHeadersPayload['Content-Type']= "application/x-www-form-urlencoded"
			self.log.debug("Created header payload for EXFO TWAMP Login API ",onDemandTwampLoginHeadersPayload)            
			self.log.debug("Creating body payload for EXFO TWAMP Login API")
			self.log.debug("Created body payload for EXFO TWAMP Login API ",onDemandTwampLoginBodyPayload)
			return onDemandTwampLoginHeadersPayload,onDemandTwampLoginBodyPayload

		elif kwargs['requestType'] == "POST_RUN":
			brixAuthToken=kwargs['brixAuthToken']
			onDemandTwampRunHeadersPayload={}
			testName=self.config.get("EMIXSourceDestMapping","test_name")
			self.log.debug("Test name ",testName)
			destNodeList=[]
			onDemandTwampRunfinalBodyPayloadDict={}
			self.log.debug("Creating body payload Dictonary for EXFO run API")
			for sourceDestMappingKey, sourceDestMappingValue in self.config.items('EMIXSourceDestMapping'):
				destNodeList=sourceDestMappingValue.split(':')
				self.log.debug("Destination node list {} for key {}".format(destNodeList,sourceDestMappingKey))
				for destNode in destNodeList:
					for siteIpMappingKey, siteIpMappingValue in self.config.items('SiteIPMappings'):
						if destNode in siteIpMappingValue.split('-'):
							onDemandTwampRunbBodyPayload={}
							paramDict={}
							paramList=[]
							paramDict['name']="target"
							paramDict['value']=siteIpMappingKey
							for key, value in self.config.items('EXFOParameters'):
								paramsDict={}
								fetchedParamsList=value.split(':')
								paramsDict['name']=fetchedParamsList[0]
								paramsDict['value']=fetchedParamsList[1]
								paramList.append(paramsDict)

							paramList.append(paramDict)
							onDemandTwampRunbBodyPayload['verifier_name']=sourceDestMappingKey.upper()+"-EMIX-BV1500"
							onDemandTwampRunbBodyPayload['test_name']=testName
							onDemandTwampRunbBodyPayload['interface_category']="twamp"
							onDemandTwampRunbBodyPayload['parameters']=paramList
							keyForFinalPayloadDict=sourceDestMappingKey.upper()+":::"+destNode							
							self.log.debug("Created body payload for key {} = {}".format(keyForFinalPayloadDict,onDemandTwampRunbBodyPayload))
							onDemandTwampRunfinalBodyPayloadDict[keyForFinalPayloadDict]=onDemandTwampRunbBodyPayload
			
			self.log.debug("Creating header payload for EXFO TWAMP run API")
			onDemandTwampRunHeadersPayload['Cookie']=brixAuthToken
			onDemandTwampRunHeadersPayload['Content-Type']="application/json"
			self.log.debug("Created header payload for EXFO TWAMP run API ",onDemandTwampRunHeadersPayload)
			return onDemandTwampRunHeadersPayload,onDemandTwampRunfinalBodyPayloadDict

		elif kwargs['requestType'] == "GET_RESULT":
			onDemandTwampResultHeadersPayload={}
			brixAuthToken=kwargs['brixAuthToken']
			self.log.debug("Creating header payload for EXFO TWAMP get result API")
			onDemandTwampResultHeadersPayload['Content-Type']= "application/x-www-form-urlencoded"
			onDemandTwampResultHeadersPayload['Cookie']=brixAuthToken
			self.log.debug("Created header payload for EXFO TWAMP get result API ",onDemandTwampResultHeadersPayload)
			return onDemandTwampResultHeadersPayload

		elif kwargs['requestType'] =="GET_LOGOFF":
			onDemandTwampLogoffHeadersPayload={}
			brixAuthToken=kwargs['brixAuthToken']
			self.log.debug("Creating header payload for EXFO TWAMP LogOff API")
			onDemandTwampLogoffHeadersPayload['Content-Type']= "application/x-www-form-urlencoded"
			onDemandTwampLogoffHeadersPayload['Cookie']=brixAuthToken
			self.log.debug("Created header payload for EXFO TWAMP LogOff API ",onDemandTwampLogoffHeadersPayload)
			return onDemandTwampLogoffHeadersPayload
		else:
			self.log.debug("Request type does not exist ")
	def generateFinalUopPayload(self, uop_payload_list, nsoResult):

		configs = re.split(r'!\sDevice', nsoResult)
		config_dict = {}
		for config in configs:
			if config != '':
				sourcenodes = re.findall(r'[:]\s\w*[^\s!?$]+',config)
				pathnames = re.findall(r'name\s\w*[^\s!?$]+',config)
				tunnel_ids = re.findall(r'\w*\stunnel_id:\w*',config)

				for sourcenode in sourcenodes:
					for (te_ids,pathname) in zip(tunnel_ids, pathnames) :
						te_ids_list = te_ids.split(':')
						te_id = te_ids_list[1]
						status = te_ids_list[0].split(' ')[0]
						pathname = pathname[5:]

						conf_list = []
						#
						# Deleted configuration
						if 'Deleted' == status:
							confs = re.findall(r'no\s+[^\n.!?]*[\.!?]*',config)
							for conf in confs:
								if (te_id in conf or pathname in conf) and 'no' in conf:
									config = config.replace(conf,'')
									conf_list.append(conf+'\n')
						#
						# Created configuration
						elif 'Created' == status:
							confs1 = re.findall(r'explicit-path\s\w*\s'+pathname+'\n[^\]*[$!]+[^\n]*[$!]',config)
							for conf in confs1:
								if (te_id in conf or pathname in conf) and 'explicit' in conf:
									conf_list.append(conf)
									config = config.replace(conf,'')

							confs2 = re.findall(r'\ninterface\stunnel-te\s'+te_id+'[^\]*[$!]+[$\nexit.!?]',config)
							for conf in confs2:
								if (te_id in conf or pathname in conf) and 'interface' in conf:
									conf_list.append(conf)
						#
						# Re-routed configuration
						else:
							confs3 = re.findall(r'explicit-path\s\w*\s'+pathname+'\n[^\]*[$!]+[^\n]*[$!]',config)
							for conf in confs3:
								if (te_id in conf or pathname in conf) and 'explicit' in conf:
									conf_list.append(conf)
									config = config.replace(conf,'')

						config_dict[sourcenode[2:] + "_t"+te_id] = conf_list
		self.log.debug( "Config dictionary", config_dict)
		uop_payload_final = []
		uop_payload_list = json.loads(uop_payload_list,strict=False)
		for uop_payload in uop_payload_list:
			lspname = uop_payload['lsp_name']
			if lspname in config_dict.keys():

				config_list = config_dict[lspname]
				final_config = ''
				for config in config_list:
					final_config = final_config + config

				uop_payload['config'] = final_config
				uop_payload_final.append(uop_payload)
		self.log.debug( "Final UOP payload", uop_payload_final)
		return json.dumps(uop_payload_final)

	def createInterfaceForOutput(self,iface,interfaceType,output):

		if(interfaceType=="congested_interfaces"):
			createdInterface=output.congested_interfaces.create()
		elif(interfaceType=="non_off_loaded_interfaces"):
			createdInterface=output.non_off_loaded_interfaces.create()

		createdInterface.intfName = iface.name
		createdInterface.intfSrcNode = iface.node.name
		createdInterface.intfDestNode = iface.opposite_interface.node.name
		createdInterface.capacity = str(iface.configured_capacity) + " Mbps"
		#returnCongestedInterfaces.traffic =	 measuredTraffic
		#returnCongestedInterfaces.utilization = measuredUtilization
		createdInterface.traffic = str(round(iface.simulated_traffic,2))+ " Mbps"
		createdInterface.utilization = str(round(iface.simulated_utilization,2)) + " %"

