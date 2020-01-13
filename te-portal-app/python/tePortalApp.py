from ncs.application import Application
from tePortalLauncher import TePortalLauncher

class TePortalApp(Application):

	def setup(self):
		try:
			self.log.info('Python App for TE-Optimization Portal starting... PLEASE WAIT...')
			self.launcher = TePortalLauncher(self)
			self.launcher.start_app()
			self.log.info('Python App for TE-Optimization Portal started, Portal is ready to use now')
		except Exception as ex:
			self.log.error('Python App for TE-Optimization Portal start failed becuase: %s' % str(ex))
			self.teardown()

	def teardown(self):
		self.log.info('Python App for TE-Optimization Portal shutting down...')
		self.launcher.stop_app()
		self.log.info('Python App for TE-Optimization Portal shutdown complete')