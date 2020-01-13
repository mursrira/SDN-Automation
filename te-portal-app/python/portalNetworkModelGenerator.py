from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from com.cisco.wae.opm.wmdClient import WMDClient
from com.cisco.wae.opm.action import TaskWorker
from contextlib import contextmanager
from tePortalLauncher import TePortalLauncher
import com.cisco.wae.design
import ConfigParser
import copy
import time
import os
import subprocess
import _ncs
import ncs

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class PortalNetworkModelGenerator(Application):

	def setup(self):
		self.log.info('portal-network-model-generator service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('portal-network-model-generator-action-point',
							 PortalNetworkModelGeneratorAction, [])

		self.log.info('portal-network-model-generator service started')

		# When this setup method is finished, all registrations are
		# considered done and the application is 'started'.


	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('portal-network-model-generator service stopped')


class PortalNetworkModelGeneratorAction(OpmActionBase):

	config = ConfigParser.RawConfigParser()

	def run(self, net_name, input, output):
		'''
			This run method provides the WAE network name that this OPM package
			is attached to, the input object with all of the user selected
			options as attributes and an output object to populate with output
			from the package, based on the Yang module defined.
		'''

		# Update opm start status - active state as True and # last run time stamp.
		self.update_start_status()

		#Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')
	

		self.log.info("Got request to update Portal network model with(delay/resv-bw):",input.update)

		start = time.time()

		if (self.nw_source == 'PLANFILE'):
			rawplanFile = self.config.get('WAEPortal','PlanFileWaeGenerated')
			with self.read_network(net_name) as network:
				network.write(rawplanFile)
				planReadTime = time.time()
				self.log.info("Raw Plan file (" + rawplanFile + ") from WAE network written in ", (planReadTime - start),
							  " seconds")
				if(input.update == 'delays' or input.update == 'both'):
					self.updateDelayInPlan()
				if(input.update == 'resv-bw' or input.update == 'both'):
					self.updateReservableBWInPLan()
				end = time.time()
				outputPlanFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
				self.log.info("End to End Plan file generation and saving to file (" + outputPlanFile + ") took ",
							  end - start, " seconds")
		elif (self.nw_source == 'WMD'):
			network_delay = self.read_network(net_name)
			network_resvBW = self.read_network(net_name)
			orig_network = self.read_network(net_name)
			if(input.update == 'delays' or input.update == 'both'):
				self.updateDelayInMemModel(network_delay)
				patch_delay = network_delay.model- orig_network.model
				if patch_delay:
					self.log.debug(patch_delay)
					source_nw = self.config.get('WAEServer', 'Topo-BGPLS-XTC-NIMO-NetworkName')
					if self._send_patch(patch_delay, source_nw):
						self.log.debug('Applying Delay patch to DARE agg complete')
				else:
					self.log.warning('No change in Delay model, no patch to send')

			if(input.update == 'resv-bw' or input.update == 'both'):
				self.updateReservableBWINMemModel(network_resvBW)
				patch_resvBW = network_resvBW.model- orig_network.model
				if patch_resvBW:
					self.log.debug(patch_resvBW)
					source_nw = self.config.get('WAEServer', 'Topo-BGPLS-XTC-NIMO-NetworkName')
					if self._send_patch(patch_resvBW, source_nw):
						self.log.debug('Applying ResvBW patch to DARE agg complete')
				else:
					self.log.warning('No change in ResvBW model, no patch to send')

				end = time.time()
				self.log.info("End to End Delay/ResvBW updates to WMD took ",
							  end - start, " seconds")
						  
			network_delay.remove_from_rpc()
			network_delay.close()
			network_resvBW.remove_from_rpc()
			network_resvBW.close()
			orig_network.remove_from_rpc()
			orig_network.close()

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

	def updateDelayInMemModel(self,network):
		self.log.info("Updating Delay in network model(local copy)")
		delaystart = time.time()
		finalDelays = self.extractDelayValuesfromFile()
		key_val_delays = {}
		interfaceDelaysFile = self.config.get('WAEPortal', 'InterfaceDelaysFile')

		# writting to text file delay counters
		with open(interfaceDelaysFile, 'w') as ifCmdFile:
			for delay in finalDelays:
				ifCmdFile.write(delay + "\n")
				tokens = delay.split(":")
				key_val_delays[tokens[0]+":"+tokens[1]+":"+tokens[2]+":"+tokens[3]] = tokens[4]

		# inserting in model
		count = 0
		circuits = network.model.circuits
		for circuit in circuits:
			count = count + 1
			srcNode = circuit.interface_a.node.name
			srcIF = circuit.interface_a.name
			destNode = circuit.interface_b.node.name
			destIF = circuit.interface_b.name
			circuit_key = srcNode+":"+srcIF+":"+destNode+":"+destIF
			circuit_key_reverse = destNode+":"+destIF+":"+srcNode+":"+srcIF
			try:
				circuit_delay = key_val_delays[circuit_key]
			except KeyError:
				circuit_delay = -1
				
			try:
				circuit_delay_reverse = key_val_delays[circuit_key_reverse]
			except KeyError:
				circuit_delay_reverse = circuit_delay
			
			if(circuit_delay != -1 and circuit_delay_reverse != -1):
				final_delay = ((float(circuit_delay) + float(circuit_delay_reverse))/2)
			if(circuit_delay == -1 and circuit_delay_reverse == -1):
				self.log.warning(str(count), ") Ignoring circuit ",circuit_key," for delay updation, because its Delay was not collected")
				continue
			elif(circuit_delay == -1):
				final_delay = float(circuit_delay_reverse)
			else:
				final_delay = float(circuit_delay)
			self.log.debug(str(count), ") Updating Delay for:", circuit_key, " val:", final_delay,", avg of delays-",circuit_delay,":",circuit_delay_reverse)
			circuit.delay = final_delay
			

		delayEnd = time.time()
		self.log.info("Updating %s Delay in network model(local copy) took "%str(count),(delayEnd - delaystart), " seconds")

	def updateReservableBWINMemModel(self,network):
		self.log.info("Updating Reservable BW in network model(local copy)")
		bwStart = time.time()
		bwThresholdPercentage = self.config.get('WAEPortal', 'InterfaceMaxAllowedBWForResBWComputation')
		factor = float(bwThresholdPercentage) /100
		count = 0
		interfaces = network.model.interfaces
		for intf in interfaces:
			count = count + 1
			# Below to commands ruin performance badly of this script to keep commented
			#self.log.debug(str(count), ") " , intf.node.name+":"+intf.name, ' capacity: ', intf.configured_capacity, ' Traffic: ', intf.measured_traffic,
			#			   ' RsvBW: ', intf.reservable_bw)
			#self.log.debug(str(count), ") " , str(intf), ' capacity: ', intf.configured_capacity, ' Traffic: ', intf.measured_traffic,
			#			   ' RsvBW: ', intf.reservable_bw)
			configured_capacity = intf.configured_capacity
			if configured_capacity is None:
				self.log.warning(str(count), ")Ignoring circuit ", intf.node.name+":"+intf.name,
								 " for RsvBW updation, because its capacity is not known")
				continue
			cuttOff_bw = configured_capacity * factor
			measured = intf.measured_traffic
			if (type(measured) is float):
				measured_traffic = measured
			else:
				measured_traffic = 0.0
			reservable_bw = cuttOff_bw - measured_traffic
			if (reservable_bw < 0):
				reservable_bw = 0
			intf.reservable_bw = reservable_bw
			# Below to commands ruin performance badly of this script to keep commented
			#self.log.debug(str(count), ") " ,intf.node.name+":"+intf.name,' capacity: ',intf.configured_capacity,' Traffic: ',intf.measured_traffic, ' Updated RsvBW: ' ,intf.reservable_bw)
			#self.log.debug(str(count), ") ", str(intf), ' capacity: ', intf.configured_capacity,
			#			   ' Traffic: ', intf.measured_traffic, ' Updated RsvBW: ', intf.reservable_bw)

		bwEnd = time.time()
		self.log.info("Updating %s ResvBW in network model(local copy) took "%str(count), (bwEnd - bwStart), " seconds")

	def extractDelayValuesfromFile(self):
		path = self.config.get('WAEPortal', 'DevicePingOutputDir')
		PingCommandsFile = self.config.get('WAEPortal', 'PingCommandsFile')
		nameSuffix = self.config.get('WAEPortal', 'suffixToRemoveInDeviceName').strip()

		finalDelays = []
		pingDirectionMapping = {}
		start = time.time()

		suffixLen = len(nameSuffix)
		with open(PingCommandsFile) as ifCmdFile:
			content = ifCmdFile.readlines()
			for line in content:
				curr = line.strip()
				if ("Commands for" in curr):
					nodeName = curr.split(":")[1]
					if (nameSuffix and nodeName.endswith(nameSuffix)):
						nodeName = nodeName[:-suffixLen]
				if ("PINGDirection" in curr):
					pingDirections = curr.split(";")
				if ("ping " in curr):
					pingIPs = curr.split(";")
					for i in range(0, len(pingIPs) - 1):
						pingDirectionMapping[nodeName + ":" + pingIPs[i].split(" ")[1]] = pingDirections[i + 1]
			Cmdtime = time.time()
		# print("Reading Interface Delay File took "+ str(float(Cmdtime-start))+" seconds")
		# self.log.debug(pingDirectionMapping)

		for filename in os.listdir(path):
			if ".txt" not in filename:
				continue
			with open(path + "/" + filename) as ifCmdFile:
				# print(path+filename)
				content = ifCmdFile.readlines()
				for line in content:
					curr = line.strip()
					if ("#ping " in curr):
						node = curr.split('#')[0]
						if (":" in node):
							node = node[node.rfind(":") + 1:]
						else:
							node = node[1:]
						ipaddress = curr.split(" ")[1]
					if ("Success rate " in curr and "round-trip" in curr):
						delays = curr.split(" ")
						delay = delays[len(delays) - 2]
						pingKey = node + ":" + ipaddress
						if (pingDirectionMapping.get(pingKey)):
							finalDelay = pingDirectionMapping[pingKey] + ":" + str(float(delay.split("/")[1]) / 2)
							finalDelays.append(finalDelay)
							#self.log.debug(finalDelay)
		parsingtime = time.time()
		self.log.info("Parsed ping results in " + str(parsingtime - Cmdtime) + " seconds")
		# print(finalDelays)
		return finalDelays



	def updateDelayInPlan(self):
		inputPlanFile = self.config.get('WAEPortal','PlanFileWaeGenerated')
		outputPlanFile = self.config.get('WAEPortal','PlanFileWithDelay')
		mate_sql_cmd = self.config.get('WAEServer','mate_sql_cmd')
		interfaceDelaysFile = self.config.get('WAEPortal', 'InterfaceDelaysFile')
		
		finalDelays = self.extractDelayValuesfromFile()

		with open(interfaceDelaysFile,'w') as ifCmdFile:
			count = sqlcount =0
			sql = ''
			cmd = ''
			sqlList = []
			for delay in finalDelays:
				count = count + 1
				sqlcount = sqlcount + 1
				if(sqlcount>500):
					sqlList.append(sql)
					sql = ''
					sqlcount = 1
				ifCmdFile.write(delay+"\n")
				vals = delay.split(":")
		
		
				## APPROACH 1 taking around 1.2 second/ 18 interface
				sql = sql + "update circuits set Delay="+vals[4]+" where NodeA='"+vals[0]+"' and NodeB='"+ vals[2] +"' and InterfaceA='"+ vals[1]+"' and InterfaceB='" +vals[3]+"';"

				## APPROACH 2 taking around 1 second/interface
				#cmd = mate_sql_cmd+" -file "+ inputPlanFile +"  -out-file "+ outputPlanFile +" -sql \"update circuits set Delay="+vals[4]+" where NodeA='"+vals[0]+"' and NodeB='"+ vals[2] +"' and InterfaceA='"+ vals[1]+" and InterfaceB='" +vals[3]+"'\"" 	
				
				## APPROACH 3 , taking long long time
				#Below command to be used in case Interface details not available
				#cmd = mate_sql_cmd+" -file "+ inputPlanFile +"  -out-file "+ outputPlanFile +" -sql \"update circuits set Delay="+vals[2]+" where NodeA='"+vals[0]+"' and NodeB=(select Name from Nodes N,NetIntIpAddresses I where I.Ipaddress='"+vals[1]+"' and N.ipaddress=I.Node) and InterfaceB=(select DISTINCT(Interface) from NetIntIpAddresses I,NetIntInterfaces NI where I.Ipaddress='"+vals[1]+"' and NI.NetIntIndex=I.NetIntIndex)\""
						#print(cmd)
						#p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
				#p.wait()
			sqlList.append(sql)
			self.log.debug(sql)
			sqlListsize = len(sqlList)
			for index, sql in enumerate(sqlList):
				if(sqlListsize == 1):
					cmd = mate_sql_cmd + " -file "+ inputPlanFile +"  -out-file "+ outputPlanFile  +" -sql \""+sql+"\""
				elif(index == 0):
					cmd = mate_sql_cmd + " -file "+ inputPlanFile +"  -out-file "+ self.getTempPlanFileName(outputPlanFile, index) +" -sql \""+sql+"\""
				elif(index == sqlListsize - 1):
					cmd = mate_sql_cmd + " -file "+ self.getTempPlanFileName(outputPlanFile, index-1) +" -out-file "+ outputPlanFile +" -sql \""+sql+"\""
				else:
					cmd = mate_sql_cmd + " -file "+ self.getTempPlanFileName(outputPlanFile, index-1) +" -out-file "+ self.getTempPlanFileName(outputPlanFile, index) +" -sql \""+sql+"\""
				self.log.debug(cmd)
				p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
				p.wait()

			sqltime = time.time()
			self.log.info("Updated Delay for "+str(count)+" interfaces in "+ str(sqltime - parsingtime)+" seconds, saved to planfile :" +outputPlanFile)

	def getTempPlanFileName(self, outputFileName, index):
		path = outputFileName.split("/")
		PingCommandsFilesLoc = self.config.get('WAEPortal','DevicePingOutputDir')
		return PingCommandsFilesLoc+"/tmp"+ str(index) +"."+ path[len(path)-1]
		#path[len(path)-1] = "tmp"+ str(index) +"."+ path[len(path)-1]
		#return "/".join(path)

	def updateReservableBWInPLan(self):
		inputPlanFile = self.config.get('WAEPortal','PlanFileWithDelay')
		outputPlanFile = self.config.get('WAEPortal','PlanFileWithDelaynResBW')
		bwThresholdPercentage = self.config.get('WAEPortal','InterfaceMaxAllowedBWForResBWComputation')
		mate_sql_cmd = self.config.get('WAEServer','mate_sql_cmd')
		
		start = time.time()
		cmd = mate_sql_cmd + " -file "+inputPlanFile+" -out-file "+outputPlanFile+" -sql 'update interfaces set ResvBW = ((interfaces.capacity*"+str(float(bwThresholdPercentage)/float(100))+")- (select TraffMeas from InterfaceTraffic it where interfaces.node=it.node and interfaces.interface=it.interface))'"

		#print(cmd)
		p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
		p.wait()
		stmt1 = time.time()
		#print("Above statement took " + str(stmt1-start) +" seconds")

		cmd = mate_sql_cmd + " -file " +outputPlanFile+ " -out-file " +outputPlanFile + " -sql 'update interfaces set ResvBW =0 where ResvBW<0'"
		#print(cmd)
		p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
		p.wait()
		stmt2 = time.time()
		#print("Above statement took " + str(stmt2-stmt1) +" seconds")

		end = time.time()
		self.log.info("Updating Reservable BW took " + str(end-start) +" seconds,saved to planfile :" +outputPlanFile)


	def read_network(self, net_name):
		if (self.nw_source == 'PLANFILE'):
			with self.get_wae_network(net_name) as network:
				return network
		elif (self.nw_source == 'WMD'):
			return TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)
