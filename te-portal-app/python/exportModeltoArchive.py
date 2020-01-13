from ncs.application import Application
from com.cisco.wae.opm.action import OpmActionBase
from com.cisco.wae.opm.network import open_plan
from tePortalLauncher import TePortalLauncher
import threading
import ConfigParser
import time
import subprocess

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY WAE.
# ---------------------------------------------

class ExportModeltoArchive(Application):

	def setup(self):
		self.log.info('export-model-to-archive service starting..')

		# The class takes care of creating a daemon (related to the
		# service/action point).
		self.register_action('export-model-to-archive-action-point',
                                ExportModeltoArchiveAction, [])

		# When this setup method is finished, all registrations are
        # considered done and the application is 'started'.
		self.log.info('export-model-to-archive service started')

	def teardown(self):
		# When the application is finished, this teardown method will
		# be called.
		self.log.info('export-model-to-archive service stopped')


class ExportModeltoArchiveAction(OpmActionBase):

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
		# Reading configuration file for config params at runtime
		self.config.read(TePortalLauncher.portal_config_file)
		self.nw_source = self.config.get('WAEServer', 'NetworkModelSource')
		self.archive_dir = self.config.get('WAEServer', 'archive_dir')
		self.planFile = self.config.get('WAEPortal', 'PlanFileWithDelaynResBW')
		self.achive_insert_cmd = self.config.get('WAEClient', 'mate_archive_insert_cmd')

		self.log.info("Got request for Archiving latest network model")
		self.start = time.time()

		if (self.nw_source == 'PLANFILE'):
			self.get_all_lsps_mate_sql(output)
		elif (self.nw_source == 'WMD'):
			self.archive_model_wmd(output)

		EndTime = time.time()
		self.log.info("Archiving network took ",(EndTime - self.planReadTime)," seconds")
		self.log.info("Total Time taken to archive network model ",(EndTime - self.start)," seconds")

		# Update opm end status - active state as False and
        # last successful run time stamp depending on output.result.
        #self.update_end_status(output.result)

	def archive_model_wmd(self, output):
		network = TePortalLauncher.get_wmd_client().get_latest_network(refresh=True)
		self.planReadTime = time.time()
		self.log.info("WMD Network accessed in ", (self.planReadTime - self.start), " seconds")
		self.log.debug("Saving Network model to disk: ",self.planFile)
		network.write(self.planFile)
		#BUSINESS LOGIC
		#arch_insert_cmd = "/opt/wae/client/software/mate/current/bin/archive_insert"
		cmd = self.achive_insert_cmd +" -plan-file "+ self.planFile +" -archive "+ self.archive_dir
		self.log.debug(cmd)
		p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
		out, err = p.communicate()
		#out = p.stdout.read()
		self.log.debug(out)
		self.log.info("WAE Model exported to archive ",self.archive_dir)
		network.remove_from_rpc()
		network.close()
