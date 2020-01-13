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
import requests
from requests.auth import HTTPBasicAuth
from com.cisco.wae.design import ServiceConnectionManager
from helpers import Helpers
import logging
import ncs
from ncs.dp import Action
import json
from datetime import datetime

class rollback(Application):
	def setup(self):
		self.log.info('Rollback Action.........')
		self.register_action('rollback-action-point',RollbackAction, [])

	def teardown(self):
		self.log.info('Rollback Action stopped')


class RollbackAction(OpmActionBase):
	@Action.action
	def cb_action(self, uinfo, name, kp, input, output):
		my_helper = Helpers(self.log)
		try:
			if (len(input.te_interfaces) > 0):
				payload = self.generateRollbackPayload(input.te_interfaces, "dry-run",my_helper)
				nso_payload = payload[0]
				uop_complete_payload = payload[1]
				uop_com_patch_payload = payload[2]
				self.log.debug("NSO nso_payload: ", nso_payload)
				if (input.action_type == "dry-run"):
					output.message = my_helper.invokeNsoAction(nso_payload, uop_complete_payload, uop_com_patch_payload, "dry-run", input, output)
					res = output.message
				else:
					res = my_helper.invokeNsoAction(nso_payload, uop_complete_payload, uop_com_patch_payload, "dry-run", input, output)

					payload = self.generateRollbackPayload(input.te_interfaces, "commit", my_helper)
					nso_payload = payload[0]
					uop_complete_payload = payload[1]
					uop_com_patch_payload = payload[2]
					final_uop_payload = my_helper.generateFinalUopPayload(uop_complete_payload, res)
					output.message = my_helper.invokeNsoAction(nso_payload, final_uop_payload, uop_com_patch_payload, "commit", input, output)

			self.log.info(output.message) 

		except (KeyError, IndexError, ValueError, NameError, ) as err:
				self.log.error(err)
				raise err
		except Exception as e:
				self.log.error(e)
				raise Exception("Failed due to internal error. Details are logged.",e)

	def generateRollbackPayload(self, te_interfaces, action, my_helper):

		self.log.info("Generating Payload for Rollback")

		#action = input.action_type

		#Generating NSO Payload
		nso_payload = {}
		nso_payload_key = "input"
		nso_payload_value = {}

		if(action == "dry-run"):
			nso_payload_value["action-type"] = "dry-run"
		else:
			nso_payload_value["action-type"] = "commit"

		self.log.info("NSO action type : ",nso_payload_value)
		uop_complete_payload = []
		uop_com_patch_payload = []
		uop_com_payload = {}
		uop_patch_payload = {}
		te_name = srcNode =  ""
		nso_payload_all_lsps = []
		response = ""
		count = 0

		network = my_helper.read_network()
		for te_intf in te_interfaces:
			#
			# To check the action_type status and rollback_allowed
			#
			if te_intf.action_type_status == "re-routed":

				te_name = te_intf.te_name
				srcNode = te_intf.srcNode
				rollback_allowed = ''

				self.log.info("unique id : ",te_intf.unique_id)
				try:
					lsps = network.model.lsps
					#for lsp in lsps:
					#	self.log.error(lsp.name, lsp.source)
					#TODO change LSP name based on WAE release
					lsp = network.model.lsps[{'source':srcNode, 'name':srcNode+'_t'+te_name}]
					#
					#Common Value
					#
					nso_next_payload, uop_next_payload, uop_prev_payload = {}, {}, {}
					nso_next_payload["te-name"] =  uop_next_payload["te-name"] = uop_prev_payload["te-name"] = str(te_intf.te_name)
					nso_next_payload["srcNode"] =  uop_next_payload["srcNode"] = uop_prev_payload["srcNode"] = str(te_intf.srcNode)
					nso_next_payload["destNode"] =  uop_next_payload["destNode"] = uop_prev_payload["destNode"] = str(te_intf.destNode)
					nso_next_payload["pathOption"] =  uop_next_payload["pathOption"] = uop_prev_payload["pathOption"] = "1"


					interfaces = my_helper.sort_interfaces_for_lsp(lsp)
					lsp_hops = my_helper.get_hops_from_interfaces_for_lsp(interfaces)
					self.log.debug("LSP hops {}".format(lsp_hops))
					uop_prev_path_hoplist = []
					# To Retrieve Previouse Hops Details for UOP payload
					for hop in lsp_hops:
						uop_prev_path_hop = {}
						uop_prev_path_hop["step"] = str(hop['step'])
						uop_prev_path_hop["ipaddress"] = str(hop['ip_address'])
						uop_prev_path_hop["intfSrcNode"] = str(hop['intfSrcNode'])
						uop_prev_path_hoplist.append(uop_prev_path_hop)

					uop_prev_payload["hop"] = uop_prev_path_hoplist

					self.log.info("UOP PREV PATH PAYLOAD : ",uop_prev_payload)
					action_type_status = 'rollbacked'
					rollback_allowed = 'false'
					uop_next_path_hoplist = []
					nso_next_payload["operation-type"] = 're-routed'
					nso_payload_hoplist = []
					# To Retrieve Hops Details for NSO payload and Next Hops Details for UOP payload
					for hop in te_intf.hop:
						nso_payload_hop, uop_next_payload_hop = {},{}
						nso_payload_hop["step"] = uop_next_payload_hop["step"] = str(hop.step)
						nso_payload_hop["ipaddress"] = uop_next_payload_hop["ipaddress"] = str(hop.ipaddress)
						nso_payload_hoplist.append(nso_payload_hop)

						uop_next_payload_hop["intfSrcNode"] = str(hop.intfSrcNode)
						uop_next_path_hoplist.append(uop_next_payload_hop)

					nso_next_payload["hop"] = nso_payload_hoplist
					uop_next_payload["hop"] = uop_next_path_hoplist
					# To Prepare complete NSO payload
					nso_payload_all_lsps.append(nso_next_payload)
					# To Prepare UOP payload for LSPs
					uop_com_payload = my_helper.generateUopPayload(te_intf.srcNode,lsp.name,uop_prev_payload,uop_next_payload,action_type_status,rollback_allowed)
					uop_patch_payload = my_helper.generateUopPatchPayload(te_intf.unique_id,rollback_allowed)
					self.log.info("UOP Payload after return from function:", uop_com_payload)
					# To Prepare complete UOP payload for all LSPs
					uop_complete_payload.append(uop_com_payload)
					uop_com_patch_payload.append(uop_patch_payload)

				except KeyError as e:
					# TODO better  error
					self.log.error(e)
					raise e
					continue

			#
			# To check the action_type status and rollback_allowed
			#
			if te_intf.action_type_status == "created":
				uop_new_payload, uop_prev_payload , nso_next_payload = {}, {}, {}
				try:
					# To get the unique_id for created lsp from rollback table
					# where action_type_status is created and rollback_allowed is True
					if response == "" and count == 0:
						response = my_helper.invokeUOPRestApi("history", "GET", None)
						count = count+1
					#To check the response data is not empty and  success is true
					if response['meta']['success'] and response["data"] != []:
						# Retrieve data from response
						for element in response["data"]:
							uniqueid = element["unique_id"]
							#To get LSPs details if te_intf unique_id match with response data unique_id
							if uniqueid == te_intf.unique_id:
								srcNode = element["node_name"]
								lspName = element["lsp_name"]
								uop_prev_payload = element["new_state"]
								uop_new_payload = element["prev_state"]

								# To Prepare NSO Payload for LSP
								action_type_status = 'deleted'
								rollback_allowed = 'false'
								nso_next_payload["operation-type"] = 'deleted'
								nso_next_payload["te-name"] = element["new_state"]["te-name"]
								nso_next_payload["srcNode"] = element["new_state"]["srcNode"]
								nso_next_payload["destNode"] = element["new_state"]["destNode"]
								nso_next_payload["pathOption"] = "1"
								# To Prepare UOP payload for LSPs
								uop_com_payload = my_helper.generateUopPayload(srcNode,lspName,uop_prev_payload,uop_new_payload,action_type_status,rollback_allowed)
								# To get UOP patch payload to disable existing created LSP
								uop_patch_payload = my_helper.generateUopPatchPayload(te_intf.unique_id,rollback_allowed)
								# To Prepare complete NSO payload for LSP
								nso_payload_all_lsps.append(nso_next_payload)

					self.log.info("UOP Payload after return from function:", uop_com_payload)
					# To Prepare complete UOP payload for all LSPs
					uop_complete_payload.append(uop_com_payload)
					uop_com_patch_payload.append(uop_patch_payload)

				except KeyError as e:
					# TODO better  error
					self.log.error(e)
					raise e
					continue
		# To Prepare Comlete NSO input payload for all LSPs
		nso_payload_value["te-interfaces"] = nso_payload_all_lsps
		nso_payload[nso_payload_key] = nso_payload_value
		nso_payload = json.dumps(nso_payload)
		self.log.info("NSO PAYLOAD GENERATED:  ",nso_payload)

		self.log.info("Invoking NSO Action for rollback")
		# To Prepare complete UOP payload for all LSPs
		uop_complete_payload = json.dumps(uop_complete_payload)
		uop_com_patch_payload = json.dumps(uop_com_patch_payload)
		self.log.info("Complete UOP Payload Generated is: ",uop_complete_payload)
		self.log.info("Complete UOP Payload for PATCH Generated is: ",uop_com_patch_payload)
		return [nso_payload, uop_complete_payload, uop_com_patch_payload]

