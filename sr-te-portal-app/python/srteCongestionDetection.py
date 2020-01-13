from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
import time
import subprocess
import smtplib
import datetime,json
import ConfigParser,requests,json
from requests.auth import HTTPBasicAuth
from helpers import Helpers
#from json2html import *
from lspDetailsCache import LspDetailsCache
from email import encoders
from configobj import ConfigObj
from email.MIMEText import MIMEText
from email.MIMEBase import MIMEBase
from requests.auth import HTTPBasicAuth
from email.MIMEMultipart import MIMEMultipart


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------


#
#SMTP Functionality Commented out - in Future uncomment it
#

class SrteCongestionDetection(Application):

	def setup(self):
		self.log.info('srte-congestion-detection service starting..')

		self.register_action('srte-congestion-detection-action-point',
								SrteCongestionDetectionAction, [])
		self.log.info('srte-congestion-detection service started')

	def teardown(self):

		self.log.info('srte-congestion-detection service stopped')


class SrteCongestionDetectionAction(OpmActionBase):

	config = ConfigParser.RawConfigParser()

	def run(self, net_name, input, output):

		# Update opm start status - active state as True and
		# last run time stamp.
		self.update_start_status()

		#Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.my_helper = Helpers(self.log)
		self.nw_source = 'WMD' ## To Change ##self.config.get('WAEServer', 'NetworkModelSource')



		# Invoke UOP to get details

		LspDetailsCache.getInstance(self.log).refreshLSPDetailsFromUOP()


		#
		#GET LSP BW Threshold From UOP
		#
		resp_json = self.my_helper.invokeUOPRestApi('get_lsp_threshold',"GET",None)
		bwThresholdPercentage = float(resp_json['data'][0]['lsp_congestion_threshold'])

		'''emailSender = self.config.get('EmailSettings','Sender')
		emailReceiver = self.config.get('EmailSettings','Receiver')
		emailPassword = self.config.get('EmailSettings','SenderCredentials')'''

		#
		#GET EMAIL RECEIVERs
		#
		resp_json = self.my_helper.invokeUOPRestApi('get_lsp_email',"GET",None)
		emailReceiver = str(resp_json['data'][0]['lsp_email'][0:])


		self.log.debug("Email Receiver: ",emailReceiver)

		resp_json = self.my_helper.invokeUOPRestApi('get_threshold_cross_count', "GET", None)
		self.congestionCount = str(resp_json['data'][0]['threshold_cross_count'])

		emailSubject = self.config.get('EmailSettings','Subject')
		emailHeader = self.config.get('EmailSettings','Header')+" <B>"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M")+"</B><BR>"
		emailFooter= self.config.get('EmailSettings','Footer')+"<BR>"
		'''smtpServer = self.config.get('EmailSettings','SmtpServerIP')+":"+self.config.get('EmailSettings','SmtpServerPort')
		smtpServer = self.config.get('EmailSettings','SmtpServerIP')
		smtpPort = self.config.get('EmailSettings','SmtpServerPort')'''


		lsps = []
		start = time.time()

		delay_congestions, prevCongestions = self.loadCongestedTunnels()

		#Invoking function to fill delay mail table and fill delay congestion dictionary

		delay_mail_table,delay_congestions = self.fill_delay_mail(delay_congestions)

		overUtilizedInterfaces, planReadTime,network = self.get_overUtilizedInterfaces_wmd(start, bwThresholdPercentage)

		self.log.info(len(overUtilizedInterfaces), " interfaces are found over utilized")
		self.log.info(overUtilizedInterfaces)
		ifCheckTime = time.time()
		self.log.info("Circuit Utilization is checked in ",(ifCheckTime - planReadTime)," seconds")

		self.log.info("Computing LSPs passing through Over Utilized interfaces")

		congReportCount = int(self.config.get('WAECongestionDetection','congestionRecurrCountb4Reporting'))

		#Creating table for Bandwidth mail

		ifLsps = []
		out = "<TABLE border='1'><TR><TH>Interface</TH><TH>BW Utilization</TH><TH>LSP's</TH></TR>"
		for interface in overUtilizedInterfaces:
			ifName = interface.name
			ifNodeName = interface.node.name
			ifUtil = str(round(interface.measured_utilization, 2))
			anyLSP = False
			outLSP = ""
			for lsp in interface.lsps_routed_through:
				anyLSP = True
				lspKeyStr = lsp.name + ":" + lsp.source.name
				lspKey = lspKeyStr + "->" + lsp.destination.name + "(" + str(lsp.simulated_traffic) + " Mbps)"
				if (prevCongestions.has_key(lspKeyStr) and int(prevCongestions[lspKeyStr]) >= congReportCount):
					outLSP = outLSP + lspKey + "<BR>"
				ifLsps.append(lspKeyStr)
			if (anyLSP):
				out = out + "<TR><TD>" + ifNodeName + ":" + ifName + "</TD><TD>" + ifUtil + "%</TD><TD>" + outLSP + "</TD></TR>"
			else:
				out = out + "</TD></TR>"
		out = out + "</TABLE>"
		self.log.debug("All Congested LSPs ",str(ifLsps))
		lsps=list(set(ifLsps))
		self.log.debug("Unique Congested LSPs ",lsps)
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
		self.log.debug("With New LSPs and without prev LSPs ", prevCongestions)

		self.saveCongestedTunnels(prevCongestions,delay_congestions)

		lspTime = time.time()
		self.log.info("Finding Congested LSP names took ",(lspTime - ifCheckTime)," seconds")

		emailContent= emailHeader+" <BR>"+"<strong>Delay Violated LSP's</strong>"+delay_mail_table+"<br><br><br>"+"<strong>Bandwidth Violated</strong>"+out+"<BR>"+emailFooter

		#Invoking Notification API to send email

		payload = "{\"body\": \""+emailContent+"\", \"mail_to\": [\""+ emailReceiver+"\"], \"subject\": \""+emailSubject+"\"}"

		self.log.info("Emailing content", emailContent)

		response=self.my_helper.invokeUOPRestApi('lsp/notification', "POST", payload)

		self.log.debug(response.text)

	def fill_delay_mail(self,delay_congestions):
		sla_violated_lsp_count = 0
		my_helper = Helpers(self.log)
		network = my_helper.read_network()
		lsps = network.model.lsps
		delay_table = '<html><TABLE border=1><TR><TH>LSP</TH><TH>Delay</TH><TH>SLA</TH></TR>'
		delay_lsps = []
		for lsp in lsps:
			if lsp.destination is None:
				continue
			congReportCount = int(self.config.get('WAECongestionDetection','congestionRecurrCountb4Reporting'))
			lspKeyStr = lsp.name + ":" + lsp.source.name
			lspRoute = lsp.route
			interfaces = my_helper.sort_interfaces_for_lsp(lsp)
			delay = lspRoute.average_latency
			delay_sla = LspDetailsCache.getInstance(self.log).getLSPDelaySLA(lsp.source.name, lsp.name)

			sla_lspClass = LspDetailsCache.getInstance(self.log).getLSPClass(lsp.source.name, lsp.name)
			self.log.debug("LSP Delay Class ",sla_lspClass, " delay ",delay, " delay_sla ",delay_sla)
			sla_traffic = str(round(lsp.simulated_traffic,2)) + " Mbps"
			lspName = lsp.name
			lspSrcNode = lsp.source.name
			lspDstNode = lsp.destination.name

			if delay > delay_sla:
				self.log.debug("LSP ", lspName," of class ", sla_lspClass, "violating SLA ", delay_sla, "with current delay ",delay)
				if sla_lspClass == '1':
					self.log.info("Above LSP is class 1, so recording SLA violation")
					delay_lsps.append(lspKeyStr)
					self.log.info(len(delay_lsps)," LSPs violated so far")
					if(delay_congestions.has_key(lspKeyStr) and int(delay_congestions[lspKeyStr]) >= congReportCount):

						delay = str(lspRoute.average_latency) + " ms"

						delay_table = delay_table + '<TR>'
						delay_table = str(delay_table) + '<TD>' + str(lspName) + ':' + str(lspSrcNode) + ' -> '+ str(lspDstNode) +'</TD>'
						delay_table = delay_table + '<TD>' +str(delay) + '</TD>'
						delay_table = delay_table + '<TD>' + str(delay_sla) + '</TD></TR>'

		delay_table = delay_table + '</TABLE></html>'
		delay_lsps = list(set(delay_lsps))
		self.log.info(len(delay_lsps)," SLA Violation LSPs found")

		# Add new congestions and repeat recurring ones
        	for l in delay_lsps:
			if(delay_congestions.has_key(l)):
				delay_congestions[l] = delay_congestions[l]+1
			else:
				delay_congestions[l] = 1
			self.log.debug("With New Delay LSPs ", delay_congestions)

		lkeys = delay_congestions.keys()
		for lk in lkeys:
			if(lk in delay_lsps):
				continue
			else:
				del delay_congestions[lk]
		self.log.debug("Delay Table Created:" ,delay_table)

		return delay_table,delay_congestions


	def get_overUtilizedInterfaces_wmd(self, start, bwThresholdPercentage):
		overUtilizedInterfaces = []
		# APPROACH 2 , took 30 minutes to verify 4000 interface, WTH, OPM rocks
		network = TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)
		planReadTime = time.time()
		self.log.info("WMD Network Model opened in ", (planReadTime - start), " seconds")
		for interface in network.model.interfaces:
			if(type(interface.measured_utilization) is float):
				if(interface.measured_utilization >= bwThresholdPercentage):
					self.log.debug('Congested Link Utilization is {}'.format(interface.measured_utilization))
					overUtilizedInterfaces.append(interface)
			else:
				self.log.debug("BW utilization not compared for interface", interface.node.name+":"+interface.name,", because its measured traffic is not known")
		return overUtilizedInterfaces, planReadTime, network

	def loadCongestedTunnels(self):
		prevCongestions = {}
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
					prevCongestions[cols[0]] = int(cols[1])
		return delay_congestions, prevCongestions

	def saveCongestedTunnels(self,bandwidthCongestions,delayCongestions):
		congestionFile = self.config.get('WAECongestionDetection','congestedTunnelsFile')
		with open(congestionFile,'w+') as ifCmdFile:
			ifCmdFile.write('TunnelKey'+ '\t'+"CongestionOccuranceCount"+'\t'+"Delay/Bandwidth Violated"+'\n')
			for key,val in bandwidthCongestions.items():
				ifCmdFile.write(key+ '\t' + str(val)+ '\t'+ str("Bandwidth")+'\n')
			for key,val in delayCongestions.items():
				ifCmdFile.write(key+ '\t' + str(val)+ '\t'+ str("Delay")+'\n')
		self.log.info("Saved LSP's to CongestedTunnels file: ",congestionFile)

