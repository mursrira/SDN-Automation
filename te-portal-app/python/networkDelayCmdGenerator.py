from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
from contextlib import contextmanager
import com.cisco.wae.design
import ConfigParser
import time,psutil
from subprocess import Popen,PIPE,STDOUT
import subprocess,os,signal

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class NetworkDelayCmdGenerator(Application):

	def setup(self):
		self.log.info('network-delay-cmd-generator-collector service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('network-delay-cmd-generator-collector-action-point',
								NetworkDelayCmdGeneratorAction, [])

		# When this setup method is finished, all registrations are
		# considered done and the application is 'started'.
		self.log.info('network-delay-cmd-generator-collector service started')

	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('network-delay-cmd-generator-collector service stopped')


class NetworkDelayCmdGeneratorAction(OpmActionBase):

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
		#pingCmdPacketCount = self.config.get('WAEPortal','pingCmdPacketCount')

		self.log.info("Got request to prepare ping commands for whole network topology")

		pingCommands = {}
		pingCmdKeys = {}
		start = time.time()

		network = self.read_network()
		planReadTime = time.time()
		self.log.info("Network model opened in ",(planReadTime - start)," seconds")
		for circuit in network.model.circuits:
				srcNode = circuit.interface_a.node.name
				if(len(circuit.interface_a.ip_addresses)<1):
					self.log.warning(srcNode+":"+circuit.interface_a.name+" being ignored for Delay Coll as no ip-address is configured")
					continue

				destNode = circuit.interface_b.node.name
				if(len(circuit.interface_b.ip_addresses)<1):
											self.log.warning(destNode+":"+circuit.interface_a.name+" being ignored for Delay Coll as no ip-address is configured")
											continue

				srcIfIP = circuit.interface_a.ip_addresses[0]
				destIfIP = circuit.interface_b.ip_addresses[0]
				commandA = "ping "+destIfIP.split('/')[0]
				#+ " repeat "+pingCmdPacketCount
				commandAkey = circuit.interface_a.node.name+":"+circuit.interface_a.name+":"+circuit.interface_b.node.name+":"+circuit.interface_b.name
				#self.log.debug(commandA)
				try:
					pingCommands[srcNode].append(commandA)
					pingCmdKeys[srcNode].append(commandAkey)
				except KeyError:
					pingCommands[srcNode] = [commandA]
					pingCmdKeys[srcNode] = [commandAkey]

				commandB = "ping "+ srcIfIP.split('/')[0]
				#+ " repeat "+pingCmdPacketCount
				commandBkey = circuit.interface_b.node.name+":"+circuit.interface_b.name+":"+circuit.interface_a.node.name+":"+circuit.interface_a.name
								#self.log.debug(commandB)
				try:
					pingCommands[destNode].append(commandB)
					pingCmdKeys[destNode].append(commandBkey)
				except KeyError:
					pingCommands[destNode] = [commandB]
					pingCmdKeys[destNode] = [commandBkey]
		circuitRsvBWTime = time.time()
		self.log.info("Ping commands are identified in ", circuitRsvBWTime-planReadTime, " seconds")

		pingCmdFile = self.config.get('WAEPortal','PingCommandsFile')
		with open(pingCmdFile,'w') as ifCmdFile:
			for nodeKey in pingCommands:
				#TODOnodeIP = network.model.nodes[nodeKey].ip_address
				nodeIP = network.model.nodes[nodeKey].management_ip
				#self.log.debug('Commands for node:',nodeKey+":"+nodeIP )
				ifCmdFile.write('Commands for node:'+nodeKey+":"+nodeIP+"\n")
				commandlist = pingCommands[nodeKey]
				cmdKeyList = pingCmdKeys[nodeKey]
				cmdKey = ''
				cmdNode = ''
				for command in cmdKeyList:
					cmdKey=cmdKey+command+";"
				for command in commandlist:
					cmdNode=cmdNode+command+";"
				#self.log.debug(cmdKey)
				#self.log.debug(cmdNode)
				#self.log.debug("---------------------")
				ifCmdFile.write("PINGDirection;"+cmdKey+"\n")
				ifCmdFile.write(cmdNode+"\n")
				ifCmdFile.write("---------------------\n")
		PingCommandsTime = time.time()
		self.log.info("Wrote ping commands to text file in ", PingCommandsTime-circuitRsvBWTime, " seconds")
		self.log.info("End to End Ping commands generation and saving to file ("+ pingCmdFile + ") took ",PingCommandsTime-start, " seconds")

		# Update opm end status - active state as False and
		# last successful run time stamp depending on output.result.
		#self.update_end_status(output.result)

		self.log.info("Now invoking Ping commands on each network device")
		mate_get_show_cmd = self.config.get('WAEClient','mate_get_show_cmd')
		auth_file = self.config.get('WAEPortal','auth_file')
		session_type_for_ping = self.config.get('WAEPortal','session_type_for_ping')
		session_custom_prompt = self.config.get('WAEPortal', 'custom_login_prompt')
		DevicePingOutputDir = self.config.get('WAEPortal','DevicePingOutputDir')
		delay_between_ssh_n_telnet = self.config.get('WAEPortal', 'delay_between_ssh_n_telnet')
		self.log.info("Using commands from: " + pingCmdFile)

		commands_ssh,commands_telnet,processToKill = [],[],[]

		with open(pingCmdFile) as ifCmdFile:
			content = ifCmdFile.readlines()
			#self.log.info(content)
			for line in content:
				curr = line.strip()
				if("Commands for" in curr):
					ipaddress = curr.split(":")[2]
				if("ping " in curr):
					if(session_type_for_ping == "mixed"):
						cmd = self.get_get_show_command(mate_get_show_cmd, auth_file, "ssh", curr, ipaddress,
											 DevicePingOutputDir, session_custom_prompt)
						commands_ssh.append(cmd)
						cmd = self.get_get_show_command(mate_get_show_cmd, auth_file, "telnet", curr, ipaddress,
												  DevicePingOutputDir, session_custom_prompt)
						commands_telnet.append(cmd)
					else:
						cmd = self.get_get_show_command(mate_get_show_cmd, auth_file, session_type_for_ping, curr,
														ipaddress, DevicePingOutputDir, session_custom_prompt)
						if(session_type_for_ping == "ssh"):
							commands_ssh.append(cmd)
						else:
							commands_telnet.append(cmd)

			self.log.info("Firing %s ping commands using SSH sessions"%str(len(commands_ssh)))
			self.popenExecute(commands_ssh,int(10))

			if session_type_for_ping == "mixed" and delay_between_ssh_n_telnet is not None:
				self.log.info("Going to wait for next %s seconds before initiating TELNET sessions" %delay_between_ssh_n_telnet)
				time.sleep(int(delay_between_ssh_n_telnet))

			self.log.info("Firing %s ping commands using TELNET sessions"%str(len(commands_telnet)))
			self.popenExecute(commands_telnet,int(10))

			PingCommandsCmpltTime = time.time()
			self.log.info("Firing ping commands to all devices took ", PingCommandsCmpltTime-PingCommandsTime, " seconds, reponse collection may take time , Please observe ("+DevicePingOutputDir+")")
			completion_wait = 20
			self.log.info("Going to wait for next %s seconds for all ping commands to complete" %str(completion_wait))
			time.sleep(completion_wait)
			self.log.info("End to End pinging process took ", PingCommandsCmpltTime - start)
			network.remove_from_rpc()
			network.close()

	def get_get_show_command(self, mate_get_show_cmd, auth_file, session_type_for_ping, curr, ipaddress, DevicePingOutputDir, session_custom_prompt):
		cmd = mate_get_show_cmd + " -auth-file " + auth_file + " -session-type " + session_type_for_ping + " -cmd '" + curr + "' -node " + ipaddress + " -out-dir " + DevicePingOutputDir
		if (session_custom_prompt is not None):
			cmd = cmd + " -telnet-username-prompt " + session_custom_prompt
		cmd = cmd + " &"
		return  cmd

	def read_network(self):
		if (self.nw_source == 'PLANFILE'):
			planFile = self.config.get('WAEPortal', 'PlanFileWaeGenerated')
			return open_plan(planFile)
		elif (self.nw_source == 'WMD'):
			return TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)
	def popenExecute(self,cmds,timeoutThreshold):
		for cmd in cmds:
			#self.log.debug(cmd)
			pro = Popen(cmd, shell=True, stdout=PIPE, stderr=STDOUT,preexec_fn=os.setsid)
			try:
				for t in range(15):
					time.sleep(1)
					if t == timeoutThreshold:
						raise Exception
			except Exception:
				os.killpg(os.getpgid(pro.pid), signal.SIGTERM)
				self.log.debug('Killed shell command - {}'.format(cmd))
				continue
