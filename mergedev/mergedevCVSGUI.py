# -*- coding: cp1252 -*-
from cvsgui.Macro import *
from cvsgui.ColorConsole import *
from cvsgui.Cvs import *
from cvsgui.CvsEntry import *
from cvsgui.App import *
import time
import os, os.path
import re
import ConfigParser

#Copyright ISRAEL RIOS.
#Faz o merge das modificações realizadas por um usuário no período e branch indicados

class MergeDev(Macro):
    def __init__(self):
        Macro.__init__(self, "Merge Changes By Developer", MACRO_SELECTION, 0, "Merge")
        self.last_startdate = time.strftime("%Y-%m-", time.localtime())
        self.last_enddate = ""
        self.last_developer = ""
        self.last_sourcebranch = ""
        self.loadParams()

    def OnCmdUI(self, cmdui):
        self.sel = App.GetSelection()
        isValid = len(self.sel) >= 1 and not self.sel[0].IsUnknown()
        cmdui.Enable(isValid)

    def getConfigPath(self):
        return os.path.join(os.path.expanduser("~"), '.mergedev.conf')

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

    def mergeFile(self, sourceBranch, filename, sDate, cvs, console):
        dateformat = '%Y-%m-%d %H:%M:%S'
        date = time.strptime(sDate, dateformat)
        # convert to the current timezone
        date = time.localtime(time.mktime(date) - time.timezone)
        sCommitDate = time.strftime(dateformat, date)
        console << kBlue <<"Merging File %s modified in %s...\n" % (filename, sCommitDate)
        # the date of checkin minus 10 seconds
        previousDate = time.localtime(time.mktime(date) - 10)
        sBaseDate = time.strftime(dateformat, previousDate)
        console << kGreen <<"Running update with base date = %s and commit date = %s\n" %\
                (sBaseDate, sCommitDate)

        # I couldn't retrieve the previous revision so I will use the estimated previous date
        try:
            code, out, err = cvs.Run("update", "-P", "-d",
                                 "-j%s:%s" % (sourceBranch, sBaseDate),
                                 "-j%s:%s" % (sourceBranch, sCommitDate),
                                 filename)
        except Exception, e:
            console << kRed << "Exception running update(possible conflict in file): %s\n" % e.message
            return
        
        # check the output
        if out != None:
            lines = out.split("\n")
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
        
    def Run(self):
        entry = self.sel[0]
        cvs = Cvs(1)
        console = ColorConsole ()
        #get Params
        ok, developer = App.PromptEditMessage("Enter the developer name:", \
                           self.last_developer, \
                           "Merge Changes By Developer")
        if ok == 0:
            return
        if developer == "":
            console << kRed << "Please, inform the developer name\n"
            console << kNormal
            return

        ok, sourceBranch = App.PromptEditMessage("Enter the modified branch name:", \
                           self.last_sourcebranch, \
                           "Merge Changes By Developer")
        if ok == 0:
            return
        if sourceBranch == "":
            console << kRed << "Please, inform the modified branch name\n"
            console << kNormal
            return
        
        ok, sStartDate = App.PromptEditMessage("Enter the START date." + \
                                               '\nIf time were not informed 00:00 will be used.'+\
                                               '\nFormat: yyyy-mm-dd [hh:mm]', \
                           self.last_startdate, \
                           "Merge Changes By Developer")
        if ok == 0:
            return
        if self.last_enddate == "":
            self.last_enddate = sStartDate
        ok, sEndDate = App.PromptEditMessage("Enter the END date."+ \
                                             '\nIf time were not informed 23:59 will be used.'+\
                                             '\nFormat: yyyy-mm-dd [hh:mm]', \
                           self.last_enddate, \
                           "Merge Changes By Developer")
        if ok == 0:
            return
        
        self.last_developer = developer
        self.last_sourcebranch = sourceBranch
        self.last_startdate = sStartDate
        self.last_enddate = sEndDate
        # validating dates
        sTimeFormat = '%Y-%m-%d %H:%M'
        try:
            if sStartDate.find(':') < 0:
                sStartDate = sStartDate + ' 00:00';
            if sEndDate.find(':') < 0:
                sEndDate = sEndDate + ' 23:59';
            startdate = time.strptime(sStartDate, sTimeFormat)
            enddate = time.strptime(sEndDate, sTimeFormat)
        except ValueError, e:
            console << kRed << "Invalid date\n" << e.message << '\n'
            console << kNormal
            return

        self.saveParams()
        for entry in self.sel:
            try:
                self.procEntry(entry, developer, sourceBranch, sStartDate, sEndDate, cvs, console)
            except Exception, e:
                console << kRed << e.message << '\n'
                console << kNormal
                return
        console << kGreen <<"End of merge.\n"

    def procEntry(self, entry, developer, sourceBranch, sStartDate, sEndDate, cvs, console):
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
        code, out, err = cvs.Run("log", "-S", "-N",
                                 "-d%s<=%s" % (sStartDate, sEndDate),
                                 "-r%s" % sourceBranch,
                                 "-w%s" % developer,
                                 filename)
        if out == None:
            console << kRed <<"No changes were found in '%s'.\n" % entry.GetName()
            return
        
        lines= out.split('\n')
        filename = ""
        startParsing = False
        patFile = re.compile("^Working file")
        patStart = re.compile("^--------")
        patEnd = re.compile("^========")
        patDate = re.compile("^date")
        
        for line in lines:
          if patFile.match(line):
            parts = line.split(':')
            filename = parts[1].strip()
          if filename != "" and (startParsing or patStart.match(line)):
            startParsing = True

            if patDate.match(line):
              entries = line.split(';')

              for item in entries:
                posSep = item.find(':')
                token = item[0:posSep]
                if token.strip() == 'date':
                    sDate = item[posSep+1:].strip();
                    posPlus = sDate.rfind('+')
                    if posPlus >= 0:
                        sDate = sDate[0:posPlus].strip()
                    self.mergeFile(sourceBranch, filename, sDate, cvs, console)
                    break;

            elif patEnd.match(line):
                filename = ""
                startParsing = False
            
          
MergeDev()

