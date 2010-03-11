#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 1-dez-2009

# For some information about the interface used, see :
# http://cr.yp.to/checkpwd/interface.html

import os
import sys
import syslog
import PAM

INPUT_FD = 3

# try:
#         ip      = os.environ['TCPREMOTEIP']
#         port    = os.environ['TCPLOCALPORT']
# except:
#         print "Missing environment values"
#         # If checkpassword is misused, it may instead exit 2
#         sys.exit(2)


data = ""

try:
    file = os.fdopen(INPUT_FD)
    data = file.read(512)
    file.close()
except:
    print "Could not get data from file descriptor 3"
    sys.exit(2)

#ATENÇÃO: os prints podem gerar erro na tentativas posteriores

def pam_conv(auth, query_list, userData):

    resp = []
    #método chamado pelo PAM para fornecer o password
    for i in range(len(query_list)):
        query, type = query_list[i]
        if type == PAM.PAM_PROMPT_ECHO_ON:
            resp.append(('', 0))
        elif type == PAM.PAM_PROMPT_ECHO_OFF:
            resp.append((passwd, 0))
        elif type == PAM.PAM_PROMPT_ERROR_MSG or type == PAM.PAM_PROMPT_TEXT_INFO:
            #print query
            resp.append(('', 0))
        else:
            return None

    return resp

def pam_auth():
    auth = PAM.pam()
    auth.start('passwd')
    auth.set_item(PAM.PAM_USER, username)
    auth.set_item(PAM.PAM_CONV, pam_conv)
    try:
        auth.authenticate()
        auth.acct_mgmt()
    except PAM.error, resp:
        #print resp #os prints podem gerar erro na tentativas posteriores
        sys.exit(1)
    except:
        # If there is a temporary problem checking the password, checkpassword exits 111
        sys.exit(111)

(username,passwd) = data.split('\x00')[0:2]

pam_auth()

userhome = '/home/' + username
os.chdir(userhome)
env = os.environ
env['USER'] = username
env['HOME'] = userhome
try:
    os.execve(sys.argv[1], sys.argv[1:], env) # o segundo parâmetro deve conter o comando como primeiro item
    #proc = subprocess.Popen(sys.argv[1:], env=env, cwd=userhome)
    #proc.communicate()
    #sys.exit(proc.returncode)
except Exception, e:
    syslog.syslog(str(e))
    sys.exit(111)

