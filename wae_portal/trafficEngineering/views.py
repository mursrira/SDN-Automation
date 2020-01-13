# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.http import HttpResponse
#from WAEController import WAEController
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from logging.handlers import RotatingFileHandler
import ldap
import ConfigParser
import logging
import os
import requests
from requests.auth import HTTPBasicAuth
import json
from requests.auth import HTTPBasicAuth
import ast
import random

#WAE-SERVER_Authentication
username = 'admin'
password = 'admin'

config = ConfigParser.RawConfigParser()
config.read(os.path.join(os.path.abspath(os.path.dirname(__file__)),'config.properties'))

######Logs Part##########
LEVELS = {'debug': logging.DEBUG,
		  'info': logging.INFO,
		  'warning': logging.WARNING,
		  'error': logging.ERROR,
		  'critical': logging.CRITICAL}

log_datefmt = config.get('Logging','datefmt')
log_filename = config.get('Logging','logFilename')
log_format = config.get('Logging','logFormat')
log_fileSize = int(config.get('Logging','logFileMaxBytes'))
log_fileCount = int(config.get('Logging','logFileMaxCount'))
log_level = LEVELS.get(config.get('Logging','logLevel'), logging.ERROR)

formatter = logging.Formatter(log_format,log_datefmt)
handler = logging.handlers.RotatingFileHandler(filename=log_filename,maxBytes=log_fileSize,backupCount=log_fileCount,encoding=None,delay=0)
logger  = logging.getLogger('PCCWLogger')
logger.setLevel(log_level)
handler.setFormatter(formatter)
logger.addHandler(handler)

######################


###




@csrf_exempt
def get_next_tunnel_id():
	tunnel_id_file = config.get('WAEPortal', 'NextTunnelIdFile')
	with open(tunnel_id_file) as ifCmdFile:
		content = ifCmdFile.readlines()
		for line in content:
			tunnel_id = str(line).rstrip()
			return tunnel_id
@csrf_exempt
def update_next_tunnel_id(tunnel_id):
	next_tunnel_id = str(int(tunnel_id)+1)
	tunnel_id_file = config.get('WAEPortal', 'NextTunnelIdFile')
	with open(tunnel_id_file, 'w') as ifCmdFile:
		ifCmdFile.write(next_tunnel_id + "\n")

###



@csrf_exempt
#@csrf_protect
def index(request):
	return render(request, 'trafficEngineering/login.html')


@csrf_exempt
#@csrf_protect
def ldap_auth(userName,passWord):
	logger.info("LDAP authentication initiated for User: "+userName)
	try:
		ipaddress = config.get('LdapAuths', 'ldapServer')

		dnPrefix = config.get('LdapAuths', 'ldapUsrDNPrefix')
		dnSufix = config.get('LdapAuths', 'ldapUsrDNSufix')

		l = ldap.initialize("ldaps://"+ipaddress)
		#l = ldap.open(ipaddress)

		#user authentication
		l.simple_bind_s(dnPrefix+userName+dnSufix, passWord)

		#Group authentication for user
		username = config.get('LdapAuths', 'ldapQryBindName')
		passwd = config.get('LdapAuths', 'ldapQryBindPwd')
		l.simple_bind_s(username, passwd)

		group_dn = config.get('LdapAuths', 'ldapAllowedGrpDn')
		dn, entry = l.search_s(group_dn, ldap.SCOPE_BASE)[0]
		member_list = entry['memberUid']
		if(not userName in member_list):
			logger.error('Usename '+ userName +' is NOT member of valid group')
			return False

		logger.debug("User "+ userName+ " authenticated sucessfully")
		return True
	except ldap.INVALID_CREDENTIALS:
		l.unbind()
		logger.error('Wrong username or password for '+userName)
	except ldap.SERVER_DOWN:
		logger.error('LDAP server not available')
	except ldap.LDAPError as e:
		logger.error('LDAP authentication error '+e)
	return False

@csrf_exempt
#@csrf_protect
def isActiveUserSession(request):
	logger.debug("Checking if current user session active")
	userName = ""
	try:
		userName = request.session['user']
		if userName == "":
			return False
		else:
			logger.debug("User session still active for user: "+str(userName))
			return True
	except KeyError:
		return False

@csrf_exempt
#@csrf_protect
@never_cache
#@login_required(login_url='/login')
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def login(request):
	logger.debug("Authenticating login request received via portal")
	if request.method =='POST':
		userName = str(request.POST.get('user',False))
		passWord = str(request.POST.get('pass',False))
		
		#######For Super User, readiing credentials frm properties file##########
		superuser = config.get('SuperUserAuths', 'username')		
		passwd_superuser = config.get('SuperUserAuths', 'password')
		###############################
		
		if(userName == superuser):
			if( passWord == passwd_superuser):
				logger.debug("Super User Login credentials are correct!!, Signing in the portal.")
				request.session['user'] = userName	
				return render(request,'trafficEngineering/mainpage.html')
			else:
                        	return render(request,'trafficEngineering/incorrect_loginpage.html')
		elif (ldap_auth(userName,passWord)):
						request.session['user'] = userName
						return render(request,'trafficEngineering/mainpage.html')
		else:	
			return render(request,'trafficEngineering/incorrect_loginpage.html')
	else:
		if(isActiveUserSession(request)):
					return render(request,'trafficEngineering/mainpage.html')
		else:
					return render(request,'trafficEngineering/login.html')

@csrf_exempt
#@csrf_protect
def logout(request):
	logger.debug("Logging out user from portal")
	try:
		del request.session['user']
	except KeyError:
		pass
	request.session.flush()
	return render(request, 'trafficEngineering/login.html')


@csrf_exempt
#@csrf_protect
def ajaxCurrentPath(request):
	lspval = str(request.POST.get('lsp',False)).strip()
	opmModuleName = "lsp-get-path"
	logger.info("Got request for current path of tunnel: "+lspval)

	if(not isActiveUserSession(request)):
			return HttpResponse("error",status=500)

	lspval = lspval.strip()
	lsp_sel_part = lspval.split(':::')
	logger.debug("Current path being fetched for tunnel: "+ str(lsp_sel_part[0]) +":" +str(lsp_sel_part[1]))

	url = getRestURL(opmModuleName)	
	payload = "{\"input\": { \"lspName\": \""+lsp_sel_part[0]+"\",\"lspSrcNode\": \""+lsp_sel_part[1]+"\" }}"
	restResponse = invokeRest(url,payload)

	if(restResponse.content==''):
		lspPaths = []
		return render(request, 'trafficEngineering/mainpage_CurrentPath_table.html', {'lspPaths':lspPaths,'lspval':lspval})
	
	res_json = json.loads(restResponse.content, strict=False)
	logger.debug("Tunnel path being responded for tunnel: "+str(lsp_sel_part)+ str(res_json))
	
	if('errors' in res_json):
		return HttpResponse("Error while communicating with OPM module("+opmModuleName+"):" +res_json['errors']['error'][0]['error-message'],status=500)

	lspPaths = res_json[opmModuleName+':output']['lspPath']

	return render(request, 'trafficEngineering/mainpage_CurrentPath_table.html', {'lspPaths':lspPaths,'lspval':lspval})


@csrf_exempt
#@csrf_protect
def ajaxgetallLsp(request):
	logger.info("Got request for to fetch all Tunnels via portal")
	opmModuleName = "lsp-fetch-all"

	if(not isActiveUserSession(request)):
		return HttpResponse("error",status=500)
	
	url = getRestURL(opmModuleName)
	payload = ""
	restResponse = invokeRest(url,payload)

	try:
		res_json = json.loads(restResponse.content, strict=False)
	except:
		return HttpResponse("No LSPs are available in network model.\nMake sure WAE collection is working fine (wae-java-vm.log)." ,status=500)
 
	if('errors' in res_json):
		return HttpResponse("Error while communicating with OPM module("+opmModuleName+"):" +res_json['errors']['error'][0]['error-message'],status=500)
	
	logger.debug("Tunnels being responded via portal are: ",res_json)
	lspList = res_json[opmModuleName+':output']['lspKeys']
	
	return render(request, 'trafficEngineering/mainpage_getAllLSP.html',{'lspList':lspList})



@csrf_exempt
#@csrf_protect
def ajaxgetoptPath(request):
	logger.info("Got request for to optimize Tunnel via portal")

	if(not isActiveUserSession(request)):
		return HttpResponse("error",status=403)
	
	### Extracting inputs provided for Optimization ###	
	##lspvalue Extraction Part
	lspval = str(request.POST.get('lsp',False)).strip()
	lspval = lspval.strip()
	lsp_sel_part = lspval.split(':::')
	
	##pathCount Part
	selPathCount = str(request.POST.get('pathCount',False))
	##lspFate Part
	selLspFate = str(request.POST.get('lspFate',False))

	##autoRoute Part
	selAutoRoute = str(request.POST.get('autoRoute',False))
	
	##exludeCrts Part
	exludeCrts = str(request.POST.get('exludeCrts',False))

	ex_crt_txt = str(request.POST.get('excludeCircuits',False))
	
	if(exludeCrts == 'true'):
		#First time optimization is clicked, lets import the trans-continental link content
		if(ex_crt_txt == ""):
			ex_crt_txt = getLinkExclusionList()
		
		circuit_lines = ex_crt_txt.splitlines()
		ex_crts_Str = "\"excludeCircuits\":["
		found_crt = False
		for crt in circuit_lines:
			if(crt.startswith('#')):
				continue
			else:
				srcDest = crt.split('::')
				if(len(srcDest) == 2):
					src = srcDest[0].split(':')
					dest = srcDest[1].split(':')
					if(len(src) != 2 or len(dest) != 2):
						continue
					else:	
						ex_crts_Str = ex_crts_Str + "{ \"SrcNode\":\""+src[0]+ "\", \"SrcInterface\":\""+src[1]+ "\", \"DestNode\":\""+dest[0]+"\", \"DestInterface\":\""+dest[1]+"\"},"
						found_crt = True
		if(found_crt):
			ex_crts_Str = ex_crts_Str[:-1]
			ex_crts_Str = ex_crts_Str + ("]")
			payload = "{\"input\": {\"lspName\": \""+lsp_sel_part[0]+"\",\"lspSrcNode\": \""+lsp_sel_part[1]+"\",\"pathCount\": \""+selPathCount+"\", \"shutdown\":" +selLspFate+", \"autoRoute\": "+selAutoRoute+", "+ex_crts_Str +"}}"	
	else:
		ex_crt_txt = ""
		payload = "{\"input\": {\"lspName\": \""+lsp_sel_part[0]+"\",\"lspSrcNode\": \""+lsp_sel_part[1]+"\",\"pathCount\": \""+selPathCount+"\", \"shutdown\":" +selLspFate+", \"autoRoute\": "+selAutoRoute+"}}"	
	
	opmModuleName = "lsp-optm-rsvp"
	url = getRestURL(opmModuleName)
	restResponse = invokeRest(url,payload)
	
	res_json = json.loads(restResponse.content, strict=False)
	
	logger.debug("Optimized paths for Tunnel being responded via portal are: ",res_json)
	
	if('errors' in res_json):
		return HttpResponse("Error while communicating with OPM module: " +res_json['errors']['error'][0]['error-message'],status=500)

	lspOptPaths = res_json[opmModuleName+':output']['lspPath']
	return render(request, 'trafficEngineering/mainpage_optimisedPaths_table.html',{'lspOptPaths':lspOptPaths,'excludeCircuits':ex_crt_txt,'exludeCrts':exludeCrts})



@csrf_exempt
#@csrf_protect
def ajaxShowConfig(request):
	logger.info("Got request for to show device configuraitons for Tunnel provisioining via portal")
	opmModuleName = "lsp-prov-commit"
	if(not isActiveUserSession(request)):
		return HttpResponse("error",status=403)

	#TODO
	'''status = device_syncup(request)

	

	if(status is not None and status!=""):
		return HttpResponse(status,status=500)'''

	nso_server = config.get('NSOServer', 'ServerRestURL')	
	url = 'http://'+nso_server+'/api/running/action/lsp-create/_operations/'
	payload,tunnel_id = getDryRunOrCommitPayload(request,"dry-run")

	logger.info("Invoking WAE to get device configuraitons for Tunnel provisioining via portal")
	restResponse = invokeRestToNSO(url,payload)

	res_json = json.loads(restResponse.content, strict=False)


	logger.debug("Device configurations being responded via portal are: {}".format(res_json))

	if('errors' in res_json):
		return HttpResponse("Error while communicating with OPM module: " +res_json['errors']['error'][0]['error-message'],status=500)
	
	resp = res_json['lsp-create:output']['message']

	return HttpResponse(resp)
	#render(request, 'trafficEngineering/mainpage_getAllLSP.html',{'lspList':lspList})

@csrf_exempt
#@csrf_protect
def ajaxApplyConfig(request):
	logger.info("Got request for Tunnel provisioining via portal")
	opmModuleName = "lsp-prov-commit"

	if(not isActiveUserSession(request)):
		return HttpResponse("error",status=403)
	#TODO

	'''status = device_syncup(request)
	if(status is not None and status!=""):
		return HttpResponse(status,status=500)'''
	nso_server = config.get('NSOServer', 'ServerRestURL')	
	url = 'http://'+nso_server+'/api/running/action/lsp-create/_operations/'
	payload,tunnel_id = getDryRunOrCommitPayload(request,"commit")

	logger.info("Invoking WAE for Tunnel provisioining via portal")
	restResponse = invokeRestToNSO(url,payload)

	res_json = json.loads(restResponse.content, strict=False)
	logger.debug("Device configurations being responded via portal are: {} ".format(res_json))

	if('errors' in res_json):
		return HttpResponse("Error while communicating with OPM module: " +res_json['errors']['error'][0]['error-message'],status=500)

	if res_json['lsp-create:output']['result']: 
		resp = res_json['lsp-create:output']['message']
		
		#updating tunnel ID on successfull tunnel deployment
		update_next_tunnel_id(tunnel_id)
	else:
		resp = 'Unable to create new Tunnel with ID - ' + str(tunnel_id)
	return HttpResponse(resp)


def getDryRunOrCommitPayload(request,action):
	completepath = request.POST.get('completepath',False).encode('ascii','ignore')
	jsonhops = json.dumps(ast.literal_eval(completepath))
	hopsJson = json.loads(jsonhops)
	hopCounts = len(hopsJson['hop'])
	hops = hopsJson['hop']
	

	hopString = "{ \"path-option\":" + str(hopsJson['pathOption'])+", \"hop\":["
	for i in range(0,hopCounts):
			hopString = hopString + "{ \"step\":"+str(hops[i]['step']) + ", \"hop-node\":\""+hops[i]['remote_node']+ "\", \"hop-ip\":\""+hops[i]['remote_ifipadd'].split('/')[0]+"\", \"hop-if\":\""+hops[i]['remote_ifname']+"\"},"
			dest = hops[i]['remote_node']
	lspSrcNodeIntfName = str(hops[0]['local_ifname'])
	logger.debug("lspSrcNodeIntfName is : {} ".format(lspSrcNodeIntfName))
	hopString = hopString[:-1]
	hopString = hopString + ("]}")

	### Extracting inputs provided for Optimization ###
	##lspvalue Extraction Part
	lspval = str(request.POST.get('lsp',False)).strip()
	lspval = lspval.strip()
	lsp_sel_part = lspval.split(':::')

	network = config.get('WAEServer', 'OPMRestAPIFinalNetworkName')

	##TODOVISHAL autoRoute Part, May need to add to lower box
	selAutoRoute = str(request.POST.get('autoRoute',False))

	## TODOVISHAL
	#tunnel_id = random.randint(100,999)
	tunnel_id = get_next_tunnel_id()
	#TODO (Vishal Code)
	#payload = "{\"input\": {\"tunnel-id\": \""+tunnel_id+"\",\"lsp-name\": \""+lsp_sel_part[0]+"_"+str(lsp_sel_part[2])+"\",\"source\": \""+lsp_sel_part[1]+"\",\"destination\": \""+dest+"\", \"auto-route\": "+selAutoRoute+",\"action-type\": \""+action+"\",\"tunnel-id\":"+str(tunnel_id)+",\"lsp-path\":[" +hopString+"]}}"
	#TODO (Murali Added)
	payload = "{\"input\": {\"tunnel-id\": \""+tunnel_id+"\",\"lsp-name\": \""+lspSrcNodeIntfName+"\",\"source\": \""+lsp_sel_part[1]+"\",\"destination\": \""+dest+"\", \"auto-route\": "+selAutoRoute+",\"action-type\": \""+action+"\",\"tunnel-id\":"+str(tunnel_id)+",\"lsp-path\":[" +hopString+"]}}"
	#payload = "{\"input\": {\"network-name\": \""+network+"\",\"lsp-name\": \""+lsp_sel_part[0]+"_"+str(lsp_sel_part[2])+"\",\"source\": \""+lsp_sel_part[1]+"\",\"destination\": \""+dest+"\", \"auto-route\": "+selAutoRoute+",\"tunnel-id\":"+str(tunnel_id)+",\"lsp-path\":[" +hopString+"]}}"
	return payload,tunnel_id

def getRestURL(opmName):
	server = config.get('WAEServer', 'OPMRestAPIServer')
	network = config.get('WAEServer', 'OPMRestAPIFinalNetworkName')
	url = "http://"+server+"/api/running/networks/network/"+network+"/opm/"+opmName+":"+opmName+"/_operations/run"
	return url

def invokeRest(url, payload):
	logger.debug("Invoking rest API with url: "+url +" and payload: "+payload)
	username = config.get('WAEServer', 'OPMRestAPIUserName')
	password = config.get('WAEServer', 'OPMRestAPIUserPass')
	headers = {
			'content-type': "application/vnd.yang.operation+json",
			}
	response=requests.request("POST", url ,auth=HTTPBasicAuth(username, password),data=payload, headers=headers)
	logger.debug("Rest response from OPM :"+response.content)
	return response

def invokeRestToNSO(url, payload):
	logger.debug("Invoking rest API to NSO with url: "+url +" and payload: "+payload)
	try:
		username = config.get('NSOServer', 'RestAPIUserName')
		password = config.get('NSOServer', 'RestAPIUserPass')
		headers = {
						'content-type': "application/vnd.yang.operation+json",
						}
		response=requests.request("POST", url ,auth=HTTPBasicAuth(username, password),data=payload, headers=headers)
		logger.debug("Rest response from NSO :"+response.content)
		return response
	except Error as e:
		logger.error("Unable to connect to NSO:" + e)
		raise e
		
def getLinkExclusionList():
	with open(config.get('WAEPortal','ExclTransLinksFile')) as f:
		return f.read()
			
def device_syncup(request):
	logger.info("Making Sure device is synced in both NSO and WAE")
	nso_server = config.get('NSOServer', 'ServerRestURL')
	lspval = str(request.POST.get('lsp',False)).strip()
	lspval = lspval.strip()
	lsp_sel_part = lspval.split(':::')
	device_suffix = config.get('WAEPortal', 'suffixToRemoveInDeviceName')
	head_end_device = lsp_sel_part[1].replace(device_suffix,"")
	payload = ""
	err_msg = ""
	final_out = ""
	
	
	try:
		logger.info("NSO:: Checking sync status of device: "+head_end_device)
		url_nso = "http://"+nso_server+"/api/running/devices/device/"+head_end_device+"/_operations/check-sync"
		restResponse_nso = invokeRestToNSO(url_nso,payload)
		res_json = json.loads(restResponse_nso.content, strict=False)
		resp = res_json['tailf-ncs:output']['result']
		final_out = "NSO:: check-sync:"+resp+"\n"
		logger.info("NSO:: check-sync: "+resp)

		if(resp != 'in-sync'):
			logger.info("NSO:: Syncing device: "+head_end_device)
			url_nso = "http://"+nso_server+"/api/running/devices/device/"+head_end_device+"/_operations/sync-from"
			restResponse_nso = invokeRestToNSO(url_nso,payload)
			res_json = json.loads(restResponse_nso.content, strict=False)
			logger.info("NSO::"+str(res_json['tailf-ncs:output']))
			resp = res_json['tailf-ncs:output']['result']
			final_out = final_out + "NSO:: device-sync-from:"+str(resp)+"\n"
			logger.info("NSO:: Synced device: "+head_end_device+" status: "+str(resp))
			if(not resp):
				err_msg = "Syncing device: "+head_end_device+" @ NSO failed, can not proceed."
				if(res_json['tailf-ncs:output']['info']!=''):
					err_msg = err_msg + "\n" + str(res_json['tailf-ncs:output']['info'])
				logger.error(err_msg)
				return err_msg


		logger.info("NSO:: Syncing LSP-RFS for device: " + head_end_device)
		url_nso = "http://"+nso_server+"/api/running/wae-rfs/services/lsp-rfs/advanced/_operations/device-sync-node"
		payload_headend = "{\"input\": {\"input\":\""+head_end_device+"\"}}"
		#payload_headend = head_end_device
		restResponse_nso = invokeRestToNSO(url_nso,payload_headend)
		res_json = json.loads(restResponse_nso.content, strict=False)
		resp = res_json['cisco-wae-lsp-rfs-service:output']['status']
		final_out = final_out + "NSO:: lsp-rfs sync-from:"+str(resp)+"\n"
		logger.info("NSO:: Synced LSP-RFS for device: "+head_end_device+" status: "+str(resp))
		if(not resp):
			err_msg = "Syncing LSP-RFS for device: "+head_end_device+" @ NSO failed, can not proceed"
			logger.error(err_msg)
			return err_msg

		wae_server = config.get('WAEServer', 'OPMRestAPIServer')
		#nso_device_name = config.get('WAEServer', 'NSOinstanceDeviceName')
		#url_wae = "http://"+wae_server+"/api/running/devices/device/"+nso_device_name+"/config/wae-rfs:wae-rfs/services/wae-lsp-rfs-config:lsp-rfs/_operations/run-collection"
		#restResponse_nso = invokeRest(url_wae,payload)
		#res_json = json.loads(restResponse_nso.content, strict=False)
		#resp = res_json['cisco-wae-lsp-rfs-service:output']['status']
		#final_out = final_out + "WAE:: lsp-rfs sync-from:"+str(resp)+"\n"


		logger.info("WAE:: Checking sync status of device (lsa-nso)")
		url_wae = "http://"+wae_server+"/api/running/devices/_operations/check-sync"
		restResponse_nso = invokeRest(url_wae,payload)
		res_json = json.loads(restResponse_nso.content, strict=False)
		resp = res_json['tailf-ncs:output']['sync-result']
		final_out = "WAE:: devices check-sync:"+str(resp)+"\n"
		nso_status = res_json['tailf-ncs:output']['sync-result'][0]['result']
		logger.info("WAE:: devices check-sync: "+str(resp))
		if(nso_status!="in-sync"):
			logger.info("WAE:: Syncing devices (lsa-nso)")
			url_wae = "http://"+wae_server+"/api/running/devices/_operations/sync-from"
			restResponse_nso = invokeRest(url_wae,payload)
			res_json = json.loads(restResponse_nso.content, strict=False)
			try:
				resp = res_json['tailf-ncs:output']['sync-result']
			except KeyError:
				err_msg = "Syncing devices (lsa-nso) @ WAE failed, can not proceed"
				logger.error(err_msg)
				return err_msg
			#nso_device_name = res_json['tailf-ncs:output']['sync-result'][0]['device']
			final_out = final_out + "WAE:: devices sync-from:"+str(resp)+"\n"
			logger.info("WAE:: Synced devices (lsa-nso) status: "+str(resp))
			nso_status = res_json['tailf-ncs:output']['sync-result'][0]['result']
			if(not nso_status):
				err_msg = "Syncing devices (lsa-nso) @ WAE failed, can not proceed"
				logger.error(err_msg)
				return err_msg

		logger.info("WAE:: Syncing LSP-CFG-NIMO for device: "+head_end_device)
		lsp_cfg_nw_name = config.get('WAEServer', 'OPMRestAPILspConfigNimoNetworkName')
		url_wae = "http://"+wae_server+"/api/running/networks/network/"+lsp_cfg_nw_name+"/nimo/wae-lsp-config-nimo:lsp-config-nimo/advanced/_operations/device-sync-node"
		head_end_with_suffix = lsp_sel_part[1]
		payload_headend = "{\"input\": {\"input\":\""+head_end_with_suffix+"\"}}"
		restResponse = invokeRest(url_wae,payload_headend)
		res_json = json.loads(restResponse.content, strict=False)
		resp = res_json['cisco-wae-lsp-config-nimo:output']['status']
		final_out = final_out + "WAE:: lsp-cfg-nimo sync-from:"+str(resp)+"\n"
		logger.info("WAE:: Synced LSP-CFG-NIMO for device: "+head_end_device+" status: "+str(resp))
		if(not resp):
			err_msg = "Syncing LSP-CFG-NIMO for device: "+head_end_device+" @ WAE failed, can not proceed"
			logger.error(err_msg)
			return err_msg
	except Exception as ex:
		if(err_msg != ""):
			ex_err_msg = "Error while syncing device: "+head_end_device+" in both NSO and WAE. Please check portal.log" + "\n" + err_msg
		else:
			ex_err_msg = "Error while syncing device: "+head_end_device+" in both NSO and WAE"
		logger.error(ex_err_msg, str(ex))
		return ex_err_msg
	except Error as ex:
		if(err_msg != ""):
			ex_err_msg = "Error while syncing device: "+head_end_device+" in both NSO and WAE. Please check portal.log" + "\n" + err_msg
		else:
			ex_err_msg = "Error while syncing device: "+head_end_device+" in both NSO and WAE"
		logger.error(ex_err_msg, str(ex))
		return ex_err_msg
	#return HttpResponse(final_out)

