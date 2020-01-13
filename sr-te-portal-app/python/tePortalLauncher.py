from com.cisco.wae.opm.wmdClient import WMDClient
from com.cisco.wae.opm.action import TaskWorker
from com.cisco.wae.opm.network import Network
from threading import Thread, Lock
import os

class MyWMDClientModelEventHandler(TaskWorker):
    def __init__(self, wmd_client):
        super(MyWMDClientModelEventHandler, self).__init__()
        self.wmd_client = wmd_client
        self.log = wmd_client.log

    def run_task(self, action):
    	self.log.debug("Model Update event Processing: ",action)
        self.wmd_client.update_model_from_wmd()
        self.log.debug("Model Update event Processed: ",action)

class MyWMDClient(WMDClient):

	def __init__(self, app):
		super(MyWMDClient, self).__init__(app)
		self.log = app.log
		self.model_event_handler = None
		self.latest_network = None
		self.mutex = Lock()
		self.eventID = 0
		
	def set_model_event_handler(self, event_handler):
		self.model_event_handler = event_handler

	def handle_model_change(self):
		self.eventID += 1
		self.log.debug("Model Update event received: ",self.eventID)
		#Creating local thread to refresh the model, as this handle_message is single threaded
		#and will cause furhter events to be blocked if we dont free up calling thread.
		self.model_event_handler.add_task(self.eventID)
		#self.update_model_from_wmd()
		self.log.debug("Model Update event Queued: ",self.eventID)

	def update_model_from_wmd(self):
		try:
			with super(MyWMDClient, self).get_opm_network(refresh=True) as (network, service):
				self.log.debug("Cloning network obj to local")
				tmp_nw = network.clone()
				self.log.debug("Cloned network obj to local")
				self.mutex.acquire()
				self.log.debug("Aquired lock for udpate")
				if self.latest_network is not None:
					self.latest_network.remove_from_rpc()
					self.latest_network.close()
				self.latest_network = tmp_nw
				#network.close()
				self.log.debug("Releasing lock for udpate")
				self.mutex.release()
		except Exception as e:
			self.log.error("Failed to get WMD network %s" % str(e))
			raise e

	# API to be used by all actions
	def get_latest_network(self,refresh):
		self.log.debug("Fetching latest_network")
		if not TePortalLauncher.is_app_started:
			raise ValueError("Python App for TE-Optimization Portal is not yet UP. Check logs @ WAE {wae-python-vm-te-portal-app.log}.")
		self.mutex.acquire()
		self.log.debug("Aquired lock for getting latest")
		if self.latest_network is not None:
			tmp = self.latest_network.clone()
		else:
			self.log.warning("Local WMD Client dont have network model, Updating from WMD master")
			self.update_model_from_wmd()
			tmp = self.latest_network.clone()
		self.log.debug("Releasing lock for getting latest")
		self.mutex.release()
		return tmp

	def _lost_connection(self):
		self.log.debug("Loosing WMD connection.")

class TePortalLauncher(TaskWorker):
	wmd_client = None
	is_app_started = False

	portal_config_file = os.getcwd()+"/packages/sr-te-portal-app/config.properties"
	

	def __init__(self, app):
		super(TePortalLauncher, self).__init__()
		self.app = app
		self.log = app.log

	def start_app(self):
		self.setup_wmd()
		self.add_task(LaunchTask(True))
		TePortalLauncher.is_app_started = True

	def setup_wmd(self):
		TePortalLauncher.wmd_client = MyWMDClient(self)
		self.model_event_handler = MyWMDClientModelEventHandler(TePortalLauncher.wmd_client)
		TePortalLauncher.wmd_client.set_model_event_handler(self.model_event_handler)
		self.log.info("WMD Client created, now starting..")
		self.model_event_handler.start()
		TePortalLauncher.wmd_client.start()
        #self.task_worker.start()
		self.log.info("WMD Client started.")
		TePortalLauncher.wmd_client.update_model_from_wmd()
		self.log.debug("WMD first copy updated, ready to use")
		self.log.info("Current Directory : {}".format(os.getcwd()))

	def stop_app(self):
		self.teardown_wmd()
		self.add_task(LaunchTask(False))
		TePortalLauncher.is_app_started = False

	def teardown_wmd(self):
		TePortalLauncher.wmd_client.stop_listen()
		self.model_event_handler.stop()
		#TePortalLauncher.wmd_client2.stop_listen()
		self.log.debug("WMD Client stopped")

	@staticmethod
	def get_wmd_client():
		if TePortalLauncher.wmd_client is not None:
			return TePortalLauncher.wmd_client

class LaunchTask(object):
	def __init__(self, start):
		self.start = start
