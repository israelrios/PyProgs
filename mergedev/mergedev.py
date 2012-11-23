#!/usr/bin/python
# -*- coding: utf-8 -*-

#Copyright ISRAEL RIOS.
#Faz o merge das modificações realizadas por um usuário no período e branch indicados

import time
import os, os.path
import sys
import subprocess
import re
import ConfigParser
import operator
import pygtk
pygtk.require('2.0')

import gtk, gtk.glade

appdir = os.path.dirname(sys.argv[0])
dateformat = '%Y-%m-%d %H:%M:%S'

def stringToDate(sDate, sDefaultTime):
    parts = sDate.split() #separate date and time
    if len(parts) == 1:
        parts.append(sDefaultTime)
    else:
        #completes the time part
        parts[1] = parts[1] + sDefaultTime[len(parts[1]):len(sDefaultTime)]
    
    return time.strptime(" ".join(parts), dateformat)

def showMessage(text, caption, parentWindow = None, type = gtk.MESSAGE_INFO):
    dlg = gtk.MessageDialog(parentWindow, gtk.DIALOG_MODAL, type, gtk.BUTTONS_OK, text)
    #dlg.set_markup(text)
    dlg.set_title(caption)
    dlg.run()
    dlg.destroy()
    return

#Dialog
class MergeDevDialog(object):
    def __init__(self):
        self.ok = False
        self.gladexml = gtk.glade.XML(os.path.join(appdir, 'mergedev.glade'))
        self.gladexml.signal_autoconnect(self)
        
    def getStartDate(self):
        return self.getEntryText('edStartDate')
    
    def setStartDate(self, value):
        self.setEntryText('edStartDate', value)
        
    def getEntryText(self, name):
        return self.gladexml.get_widget(name).get_text()
    
    def setEntryText(self, name, text):
        self.gladexml.get_widget(name).set_text(text)

    def on_btnOk_clicked(self, button):
        self.ok = True
        try:
            if self.isValid():
                self.gladexml.get_widget("MainWindow").hide()
                gtk.main_quit()
        except Exception, e:
            showMessage(str(e), "Validation Error", type = gtk.MESSAGE_ERROR)
            
    def isValid(self):
        if self.branchName == None or self.branchName.strip() == "":
            return False
        if self.developer == None or self.developer.strip() == "":
            return False
        if self.sStartDate == None or self.sStartDate.strip() == "":
            return False
        if self.sEndDate == None or self.sEndDate.strip() == "":
            return False
        try:
            self.startDate = stringToDate(self.sStartDate, '00:00:00')
        except:
            raise Exception('Invalid Start Date.')
        try:
            self.endDate = stringToDate(self.sEndDate, '23:59:59')
        except:
            raise Exception('Invalid End Date.')
        return True
        
    def on_btnCancel_clicked(self, button):
        self.ok = False
        gtk.main_quit()
    
    def onDelete(self, event, userdata):
        self.ok = False
        gtk.main_quit()
    
    branchName = property(lambda self: self.getEntryText('edBranch'), lambda self, value: self.setEntryText('edBranch', value) )
    developer = property(lambda self: self.getEntryText('edDeveloper'), lambda self, value: self.setEntryText('edDeveloper', value) )
    sStartDate = property(getStartDate, setStartDate )
    sEndDate = property(lambda self: self.getEntryText('edEndDate'), lambda self, value: self.setEntryText('edEndDate', value) )
        
#Console compatible with cvsgui.ColorConsole
kNormal = "\033[m"
kYellow = "\033[33m"
kGreen = "\033[32m"
kMagenta = "\033[35m"
kRed = "\033[31m"
kBlue = "\033[34m"
kBold = "\033[1m"
kUnderline = "\033[4m"

class ColorConsole:
    def __init__(self):
        self << kNormal

    def __del__(self):
        self << kNormal

    def out(self, stringOrStyle):
        """Print text in the application console
        """

        sys.stdout.write(stringOrStyle)

    def __lshift__(self, stringOrStyle):
        """ex: ColorConsole() << kRed << "This is red"
        """

        sys.stdout.write(stringOrStyle)        
        return self

#Entry compatible with cvsgui.Entry
class Entry:
    def __init__(self, filename):
        self.filename = os.path.abspath(filename)
    def GetPath(self):
        return os.path.dirname(self.filename)
    def IsFile(self):
        return os.path.isfile(self.filename)
    
    def GetName(self):
        return os.path.basename(self.filename)
            
    def GetFullName(self):
        return self.filename

class MergeDev:
    def __init__(self):
        self.last_startdate = time.strftime("%Y-%m-", time.localtime())
        self.last_enddate = ""
        self.last_developer = ""
        self.last_sourcebranch = ""
        self.loadParams()

    def getConfigPath(self):
        return os.path.join(os.path.expanduser("~"), '.mergedev.conf')

    def cvsRun(self, *args):
        cmd = []
        cmd.append('cvs')
        for arg in args:
            cmd.append(arg)
        console << kGreen << ' '.join(cmd) << '\n'
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        ret = p.returncode
        if ret == None:
            ret = 0
        return (ret, out, err)

    def saveParams(self):
        try:
            cp = ConfigParser.ConfigParser()
            if not cp.has_section('params'):
                cp.add_section('params')
            if not cp.has_section('global'):
                cp.add_section('global')
            cp.set('params', 'developer', self.last_developer)
            cp.set('params', 'sourceBranch', self.last_sourcebranch)
            cp.set('global', 'version', 1) #one day may be usefull
            f = open(self.getConfigPath(), 'w')
            try:
                cp.write(f)
            finally:
                f.close()
        except:
            pass

    def loadParams(self):
        try:
            cp = ConfigParser.ConfigParser(
                {'developer': self.last_developer, 'sourceBranch':self.last_sourcebranch})
            f = open(self.getConfigPath(), 'r')
            try:
                cp.readfp(f)
            finally:
                f.close()
            if cp.has_section('params'):
                self.last_developer = cp.get('params', 'developer')
                self.last_sourcebranch = cp.get('params', 'sourceBranch')
        except:
            pass

    def mergeFileByDate(self, sourceBranch, filename, sDate):
        dateformat = '%Y-%m-%d %H:%M:%S'
        date = time.strptime(sDate, dateformat)
        # convert to the current timezone
        date = time.localtime(time.mktime(date) - time.timezone)
        sCommitDate = time.strftime(dateformat, date)
        console << kBlue <<"Merging File %s modified in %s...\n" % (filename, sCommitDate)
        # the date of checkin minus 10 seconds
        previousDate = time.localtime(time.mktime(date) - 1)
        sBaseDate = time.strftime(dateformat, previousDate)
        console << kGreen <<"Running update with base date = %s and commit date = %s\n" %\
                (sBaseDate, sCommitDate)

        # I couldn't retrieve the previous revision so I will use the estimated previous date
        try:
            code, out, err = self.cvsRun("update", "-P", "-d",
                                 "-j%s:%s" % (sourceBranch, sBaseDate),
                                 "-j%s:%s" % (sourceBranch, sCommitDate),
                                 filename)
        except Exception, e:
            console << kRed << "Exception running update(possible conflict in file): %s\n" % str(e)
            return
        
        self.checkUpdateOutput(filename, code, out, err)
    
    def mergeFileByRev(self, filename, rev):
        oldrev = self.calcOldRevision(rev)
        console << kGreen <<"Running update with base revision = %s and revision = %s\n" %\
                (oldrev, rev)
        # updating using the calculated oldrev
        try:
            code, out, err = self.cvsRun("update", "-P", "-d",
                                 "-j%s" % (oldrev),
                                 "-j%s" % (rev),
                                 filename)
        except Exception, e:
            console << kRed << "Exception running update(possible conflict in file): %s\n" % str(e)
            return
        
        self.checkUpdateOutput(filename, code, out, err)
        
    def checkUpdateOutput(self, filename, code, out, err):   
        # check the output
        if out != None:
            lines = out.split('\n')
            doOutput = True
            if out.find("already contains") >= 0:
                doOutput = False
                for line in lines:
                    if line.find("already contains") >= 0:
                        console << kNormal << line << '\n'
                        break;
            if out.find("conflicts") >= 0:
                doOutput = False
                console << kRed << "WARNING: conflicts found in %s\n" % filename
                
            if doOutput and len(lines) <= 2:
                console << kNormal << out
                
        if code != 0:
            console << kRed << "Update returned errorcode = %d. Output:\n" % code
            if out != None:
                console << kRed << out
        if err != None and err.strip() != "":
            console << kRed << err
        elif out == None or out.strip() == '':
            console << kRed << "WARNING: nothing was done in file %s\n" % filename
    
    def diffFile(self, filename, rev, oldrev):
        console << kBlue <<"Diffing File %s revision %s against %s...\n" % (filename, rev, oldrev)

        # diffing using the calculated oldrev
        try:
            code, out, err = self.cvsRun("diff", "-N", "-U", "3",
                                 "-r%s" % (oldrev),
                                 "-r%s" % (rev),
                                 filename)
        except Exception, e:
            console << kRed << "Exception running diff: %s\n" % str(e)
            return
        
        if not code in [0,1]:
            console << kRed << "Diff returned errorcode = %d. Output:\n" % code
            if out != None:
                console << kRed << out
        if err != None and err.strip() != "":
            console << kRed << err
        elif code == 0 or out == None or out.strip() == '':
            console << kRed << "WARNING: no differences found in file %s\n" % filename
        else:
            f=open(self.patchfile, 'a+')
            try:
                f.write(out) #.decode('latin1').encode('utf8'))
            finally:
                f.close()

    def calcOldRevision(self, rev):
        parts = rev.split('.')
        lastnum = int(parts[len(parts)-1])
        del parts[len(parts)-1]
        lastnum -= 1
        if lastnum > 0:
            parts.append(str(lastnum))
        else:
            del parts[len(parts)-1]
            if len(parts) == 0:
                return '1.0'
        return '.'.join(parts)

    def getRepository(self):
        repo = open('CVS/Repository', 'r')
        rpath = repo.read().strip()
        repo.close()
        return rpath

    def getRootPath(self):
        rfile = open('CVS/Root', 'r')
        rpath = rfile.read().strip().split(':')[-1]
        rfile.close()
        return rpath

    def procEntry(self, entry, developer, sourceBranch, sStartDate, sEndDate):
        console << kBlue <<"Querying changes in '%s' made by %s on %s between %s and %s...\n" % \
                (entry.GetName(), developer, sourceBranch, sStartDate, sEndDate)
        if entry.IsFile():
            os.chdir( entry.GetPath())
            filename = entry.GetName()
        else:
            os.chdir( entry.GetFullName())
            filename = '.'
        #sDateCommand = "-d\"%s<=%s\"" % (sStartDate, sEndDate)
        #command = "cvs log -S -N " + sDateCommand + " -r" + sourceBranch + " -w" + developer
        #console << kNormal << command << '\n'
        if sourceBranch.upper() == 'HEAD':
            optRev = '-b'
        else:
            optRev = "-r%s" % sourceBranch

        rpath = os.path.normpath(self.getRepository() + '/' + filename)
        code, out, err = self.cvsRun("rlog", "-S", "-N",
                                 "-d%s<=%s" % (sStartDate, sEndDate),
                                 optRev, #TODO: when branch is HEAD the initial version may not be retrievied
                                 "-w%s" % developer,
                                 rpath)
        if out == None:
            console << kRed <<"No changes were found in '%s'.\n" % entry.GetName()
            return

        fullrpath = os.path.normpath(self.getRootPath()) + '/' + os.path.normpath(self.getRepository()) + '/'

        lines= out.split("\n")
        filename = ""
        startParsing = False
        fileMarker = 'RCS file:'
        patAll = re.compile(r"\n(RCS file:.*?)==================================", re.DOTALL | re.MULTILINE)
        patDate = re.compile(r"date:\s*(\d{4}\-\d{2}\-\d{2} \d{2}:\d{2}:\d{2})\s*[\-+]\d{4};")
        for mo in patAll.finditer(out):
            filelog = mo.group(1).split('\n')
            lastline = 0
            for i in range(0, len(filelog)):
                if filelog[i].startswith(fileMarker):
                    filename = filelog[i][len(fileMarker):].strip()[:-len(',v')]
                    filename = filename[len(fullrpath):]
                    lastline = i 
                    break
            i = lastline + 6
            revs = []
            while i < len(filelog):
                if filelog[i].startswith('----------------------'):
                    i += 1
                    revs.append(filelog[i][len('revision'):].strip())
                    i += 1
                    #sDate = patDate.search(filelog[i]).group(1)
                    #self.mergeFileByDate(sourceBranch, filename, sDate)
                    #self.mergeFileByRev(filename, rev);
                    i += 1
                i += 1
            filename = filename.replace('/Attic/', '/')
            revs.sort()
            irev = 0;
            while irev < len(revs):
                rev = revs[irev]
                oldrev = self.calcOldRevision(rev)
                irev += 1
                #check for sequencial revision numbers
                while irev < len(revs) and self.calcOldRevision(revs[irev]) == rev:
                    rev = revs[irev] 
                    irev += 1
                self.diffFile(filename, rev, oldrev)
                
        
    def Run(self, sel):
        #get Params
        dlg = MergeDevDialog()
        dlg.developer = self.last_developer
        dlg.branchName = self.last_sourcebranch
        if self.last_enddate == "":
            dlg.sEndDate = self.last_startdate
        else:
            dlg.sEndDate = self.last_enddate
        dlg.sStartDate = self.last_startdate
        gtk.main()
        if not dlg.ok:
            return
        developer = dlg.developer
        sourceBranch = dlg.branchName
        sStartDate = time.strftime(dateformat, dlg.startDate)
        sEndDate = time.strftime(dateformat, dlg.endDate)
        
        self.last_developer = developer
        self.last_sourcebranch = sourceBranch
        self.last_startdate = sStartDate
        self.last_enddate = sEndDate
        
        self.saveParams()
        #remove patch file if it exists.
        self.patchfile = os.path.join(os.path.abspath('.'), 'mergedev.patch')
        if os.path.exists(self.patchfile):
            os.remove(self.patchfile)
        
        for entry in sel:
            try:
                self.procEntry(entry, developer, sourceBranch, sStartDate, sEndDate)
            except Exception, e:
                console << kRed << str(e) << '\n'
                console << kNormal
                return
        console << kGreen <<"End of merge.\n"
    

console = ColorConsole()
          
md = MergeDev()
sel = []
for i in range(1, len(sys.argv)):
    sel.append(Entry(sys.argv[i]))
if len(sel) == 0:
    sel.append(Entry('.'))
md.Run(sel)

console << kNormal

