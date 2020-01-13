from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
import time
import subprocess
import smtplib
import datetime
import ConfigParser

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class LspCongestionDetection(Application):

	def setup(self):
		self.log.info('lsp-congestion-detection service starting..')
		#network - delay - cmd - generator - collector
		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('lsp-congestion-detection-action-point',
								LspCongestionDetectionAction, [])

		# When this setup method is finished, all registrations are
		# considered done and the application is 'started'.
		self.log.info('lsp-congestion-detection service started')

	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('lsp-congestion-detection service stopped')


class LspCongestionDetectionAction(OpmActionBase):

	config = ConfigParser.RawConfigParser()

	def run(self, net_name, input, output):
		'''
			This run method provides the WAE network name that this OPM package
			is attached to, the input object with all of the user selected
			options as attributes and an output object to populate with output
			from the package, based on the Yang module defined.
		'''

		# Update opm start status - active state as True and
		# last run time stamp.
		self.update_start_status()

		#Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')

		bwThresholdPercentage = float(self.config.get('WAEPortal', 'BandWidthCongestionThreshold'))
		emailSender = self.config.get('EmailSettings','Sender')
		#emailPassword = self.config.get('EmailSettings','SenderCredentials')
		emailReceiver = self.config.get('EmailSettings','Receiver')
		emailSubject = self.config.get('EmailSettings','Subject')
		emailHeader = self.config.get('EmailSettings','Header')+" <B>"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M")+"</B><BR>"
		emailFooter= self.config.get('EmailSettings','Footer')+"<BR>"
		smtpServer = self.config.get('EmailSettings','SmtpServerIP')+":"+self.config.get('EmailSettings','SmtpServerPort')


		lsps = []
		start = time.time()

		self.log.info("Got request for congestion detection and reporting")

		if (self.nw_source == 'PLANFILE'):
			overUtilizedInterfaces, planReadTime = self.get_overUtilizedInterfaces_mate_sql(start)
		elif (self.nw_source == 'WMD'):
			overUtilizedInterfaces, planReadTime,network = self.get_overUtilizedInterfaces_wmd(start)

		self.log.info(len(overUtilizedInterfaces), " interfaces are found over utilized")
		ifCheckTime = time.time()
		self.log.info("Circuit Utilization is checked in ",(ifCheckTime - planReadTime)," seconds")
		
		self.log.info("Computing LSPs passing through Over Utilized interfaces")
		prevCongestions = self.loadCongestedTunnels()
		congReportCount = int(self.config.get('WAEPortal','congestionRecurrCountb4Reporting'))-1

		ifLsps = []
		out = '<TABLE border="1"><TR><TH>Interface</TH><TH>BW Utilization</TH><TH>Affected Tunnels</TH></TR>'
		for interface in overUtilizedInterfaces:
                        ifName = interface.name
                        ifNodeName = interface.node.name
                        ifUtil = str(round(interface.measured_utilization, 2))
                        # out = out + '<TR><TD>'+ifNodeName + ":" + ifName+'</TD><TD>'+ ifUtil+'%</TD><TD>'
                        anyLSP = False 
                        outLSP = ""
                        for lsp in interface.lsps_routed_through:
                                anyLSP = True
                                lspKeyStr = lsp.name + ":" + lsp.source.name
                                lspKey = lspKeyStr + "->" + lsp.destination.name + "(" + str(
                                        lsp.measured_traffic) + " Mbps)"
                                if (prevCongestions.has_key(lspKeyStr) and int(
                                                prevCongestions[lspKeyStr]) >= congReportCount):
                                        outLSP = outLSP + lspKey + '<BR>'
                                ifLsps.append(lspKeyStr)
                        if (anyLSP):
                                out = out + '<TR><TD>' + ifNodeName + ":" + ifName + '</TD><TD>' + ifUtil + '%</TD><TD>' + outLSP + '</TD></TR>'
		# else:
		# out = out + 'none</TD></TR>'
		out = out + '</TABLE>'

		self.log.debug("All Congested LSPs ",str(ifLsps))
		lsps=list(set(ifLsps))
		self.log.debug("Unique Congested LSPs ",str(lsps))
		self.log.info(len(lsps), " LSPs are found passign through congested circuits")
		self.log.debug(out)

		# Add new congestions and repeat recurring ones		
		for l in lsps:
			if(prevCongestions.has_key(l)):
				prevCongestions[l] = prevCongestions[l]+1
			else:
				prevCongestions[l] = 1
		self.log.debug("With New LSPs ", prevCongestions)

		# Remove Congestions that didnt repeat this time from last time
		lkeys = prevCongestions.keys()
		for lk in lkeys:
			if(lk in lsps):
				continue	
			else:
				del prevCongestions[lk]
		self.log.debug("With New LSPs and wihtout prev LSPs ", prevCongestions)

		self.saveCongestedTunnels(prevCongestions)

		lspTime = time.time()
		self.log.info("Finding Congested LSP names took ",(lspTime - ifCheckTime)," seconds")

		if(len(overUtilizedInterfaces)>0):
			self.log.info("Sending Email notificaiton to ", emailReceiver)
			emailContent= "From: " + emailSender + "\n To: " + str(emailReceiver.split(',')) +"\nMIME-Version: 1.0\nContent-type: text/html\nSubject: "+emailSubject+"\n"+ emailHeader+" <BR>"+out+" <BR><BR>"+emailFooter
			self.log.debug(emailContent)
		
			try:
				smtpObj = smtplib.SMTP(smtpServer)
				smtpObj.starttls()
				#smtpObj.login(emailSender,emailPassword)
				smtpObj.sendmail(emailSender, emailReceiver.split(',') , emailContent)
				self.log.info("Successfully sent email to ", emailReceiver)
				smtpObj.quit()
			except smtplib.SMTPException as e:
				self.log.error("Error: Unable to send email ",type(e), e)
		else:
			self.log.info("No interface found over-utilized("+str(bwThresholdPercentage)+"%) so NOT sending email notification")
		"""
		except smtplib.SMTPRecipientsRefused as e:
			self.log.error("Error: Unable to send email ", e)
		except smtplib.SMTPHeloError as e:
						self.log.error("Error: Unable to send email ", e)
		except smtplib.SMTPSenderRefused as e:
						self.log.error("Error: Unable to send email ", e)
		except smtplib.SMTPDataError as e:
						self.log.error("Error: Unable to send email ", e)
		"""
			
		endTime = time.time()
		self.log.info("Overall Congestion Detection and reporting took ",endTime-start, " seconds")
		network.remove_from_rpc()
		network.close()

	def get_overUtilizedInterfaces_mate_sql(self, start):
		inputPlanFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
		mate_sql_cmd = self.config.get('WAEServer', 'mate_sql_cmd')
		bwThresholdPercentage = float(self.config.get('WAEPortal', 'BandWidthCongestionThreshold'))
		with open_plan(inputPlanFile) as network:
			planReadTime = time.time()
			self.log.info("Plan file opened in ", (planReadTime - start), " seconds")

			# APPROACH 1, took 2 seconds to verify 4000 interface
			sql = "select IT.TraffMeas,I.capacity,I.Node,I.Interface from interfaces I,InterfaceTraffic IT where IT.Node=I.Node and IT.Interface=I.Interface and (IT.TraffMeas>I.capacity*" + str(
				bwThresholdPercentage / float(100)) + ")"
			cmd = mate_sql_cmd + " -file " + inputPlanFile + "  -sql \"" + sql + "\""
			self.log.debug(cmd)
			p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
			out, err = p.communicate()
			# out = p.stdout.read()
			self.log.debug(out)

			lines = out.split('\n')
			headerPassed = False
			overUtilizedInterfaces = []
			for line in lines:
				line = line.strip()
				if (headerPassed):
					vals = line.split('\t')
					if (len(vals) < 4):
						continue
					overUtilizedInterfaces.append(network.model.interfaces[{'name': vals[3], 'node': vals[2]}])
				elif ("TraffMeas" in line):
					headerPassed = True
		return overUtilizedInterfaces, planReadTime

	def get_overUtilizedInterfaces_wmd(self, start):
		bwThresholdPercentage = float(self.config.get('WAEPortal', 'BandWidthCongestionThreshold'))
		overUtilizedInterfaces = []
		# APPROACH 2 , took 30 minutes to verify 4000 interface, WTH, OPM rocks
		network = TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)
		planReadTime = time.time()
		self.log.info("WMD Network Model opened in ", (planReadTime - start), " seconds")
		for interface in network.model.interfaces:
			if(type(interface.measured_utilization) is float):
				if(interface.measured_utilization >= bwThresholdPercentage):
					overUtilizedInterfaces.append(interface)
			else:
				self.log.debug("BW utilization not compared for interface", interface.node.name+":"+interface.name,", because its measured traffic is not known")
		return overUtilizedInterfaces, planReadTime, network

	def loadCongestedTunnels(self):
		prevCongestions = {}
		congestionCount = self.config.get('WAEPortal','congestionRecurrCountb4Reporting')
		congestionFile = self.config.get('WAEPortal','congestedTunnelsFile')
		with open(congestionFile) as ifCmdFile:
			content = ifCmdFile.readlines()
			count = 1
			for line in content:
				count = count + 1
				if(count<=2):
					continue
				cols = line.strip().split('\t')
				prevCongestions[cols[0]] = int(cols[1])
		return prevCongestions

	def saveCongestedTunnels(self,congestions):
		congestionFile = self.config.get('WAEPortal','congestedTunnelsFile')
		with open(congestionFile,'w') as ifCmdFile:
			ifCmdFile.write('TunnelKey'+ '\t'+"CongestionOccuranceCount"+'\n')
			for key,val in congestions.items():
				ifCmdFile.write(key+ '\t' + str(val)+'\n')

