#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 11-jun-2012
import os
import ftplib
import getpass
import hashlib
import zlib
import cStringIO
import time

class FileInfo(object):
    def __init__(self, isdir, key=None, date=None):
        self.isdir = isdir
        self.key = key
        self.date = date

class DirInfo(dict):
    def __init__(self, path, version = 1, generated = time.ctime()):
        self.path = path
        self.version = version
        self.generated = generated

    def parse(self, lines):
        self.version = int(lines[0])
        self.generated = time.strptime(lines[1])
        for line in lines[2:]:
            (filename, isdir, key, date) = line.split(';')
            self[filename] = FileInfo(isdir == 'True', key, date)

class FtpSync(object):
    bkpdirname = 'bkp_dir'
    dirinfoname = "dirinfo__.bkp"
    def __init__(self, server, username, passwd):
        object.__init__(self)
        self.ftp = ftplib.FTP(server, username, passwd)
        self.curdir = '/'
        self.remotelistcache = {}
        self.dirinfos = {}
        self.mustsavedirinfo = False
        self.checkeddirs = set()

    def changedir(self, remotedir):
        if remotedir != '/':
            remotedir = remotedir.rstrip('/')
        if remotedir != self.curdir:
            if self.mustsavedirinfo:
                self.savedirinfo(self.curdir)
            print "* Changing dir", remotedir
            self.ftp.cwd(remotedir)
            self.curdir = remotedir

    def filelist(self, dirname):
        lst = []
        pathstart = len(dirname) + 1
        for dirpath, dirs, files in os.walk(dirname):
            for filename in files + dirs:
                if filename != self.dirinfoname:
                    lst.append(os.path.join(dirpath[pathstart:], filename))
        return lst

    def remotelist(self, path):
        if path in self.remotelistcache:
            return self.remotelistcache[path]
        self.changedir(path)
        print "* Listing dir", path
        lst = self.ftp.nlst()
        self.remotelistcache[path] = lst
        return lst

    def mkdirs(self, dirname):
        """ Cria diretórios remotamente. """
        parent = '/'
        for name in dirname.strip('/').split('/'):
            if parent == '/':
                fullpath = parent + name
            else:
                fullpath = parent + '/' + name
            if not name in self.remotelist(parent):
                print "* Creating dir", fullpath
                self.ftp.mkd(fullpath)
                if parent in self.remotelistcache:
                    self.remotelistcache[parent].append(name)
                self.remotelistcache[fullpath] = []
            parent = fullpath

    def remotedir(self, dirname):
        dirname = (self.repo + '/' + dirname.replace(os.sep, '/')).rstrip('/')
        dirname = dirname.encode('latin1').encode('quopri')
        if dirname != self.curdir:
            self.mkdirs(dirname)
            self.changedir(dirname)
        return dirname

    def getdirinfo(self, remotedir):
        if remotedir in self.dirinfos:
            return self.dirinfos[remotedir]
        dirinfo = DirInfo(remotedir)
        if self.dirinfoname in self.remotelist(remotedir):
            self.changedir(remotedir)
            print "* Reading", self.dirinfoname
            lines = []
            def newline(line):
                lines.append(line.decode('utf8'))
            self.ftp.retrlines('RETR ' + self.dirinfoname, newline)
            dirinfo.parse(lines)
        self.dirinfos[remotedir] = dirinfo
        return dirinfo

    def formatdirinfo(self, dirinfo):
        # linha 0: versão
        # linha 1: data de geração
        lines = ['1', time.ctime()]
        for filename, fileinfo in dirinfo.items():
            lines.append(';'.join([filename, str(fileinfo.isdir), fileinfo.key, fileinfo.date]))
        return '\n'.join(lines).encode('utf8')

    def savedirinfo(self, remotedir):
        if not remotedir in self.dirinfos:
            return
        dirinfo = self.dirinfos[remotedir]
        self.changedir(remotedir)
        self.store(self.dirinfoname, self.formatdirinfo(dirinfo), binary=False)
        self.mustsavedirinfo = False

    def copyfile(self, filepath):
        (dirname, filename) = os.path.split(filepath)
        rdir = self.remotedir(dirname)
        print filepath
        dirinfo = self.getdirinfo(rdir)
        with open(filepath, 'rb') as f:
            data = f.read()
        # key computation
        key = hashlib.sha1()
        key.update(filename.encode('utf8'))
        key.update(data)
        filekey = key.hexdigest()

        if filename in dirinfo:
            oldkey = dirinfo[filename].key
            if oldkey == filekey: # same key?
                return
            if oldkey in self.remotelist(rdir):
                self.deletefile(oldkey, False)

        data = zlib.compress(data)
        self.store(filekey, data)
        # dirinfo
        filedate = time.ctime(os.path.getmtime(filepath))
        dirinfo[filename] = FileInfo(False, filekey, filedate)
        self.mustsavedirinfo = True

    def savedir(self, filepath):
        (dirname, filename) = os.path.split(filepath)
        rdir = self.remotedir(dirname)
        print filepath
        dirinfo = self.getdirinfo(rdir)
        if filename in dirinfo:
            return
        filedate = time.ctime(os.path.getmtime(filepath))
        dirinfo[filename] = FileInfo(True, filename.encode('latin1').encode('quopri'), filedate)
        self.mustsavedirinfo = True

    def store(self, filename, data, binary=True):
        print "* Storing", filename.encode('utf8')
        if binary:
            self.ftp.storbinary('STOR ' + filename, cStringIO.StringIO(data))
        else:
            self.ftp.storlines('STOR ' + filename, cStringIO.StringIO(data))
        if self.curdir in self.remotelistcache:
            self.remotelistcache[self.curdir].append(filename)

    def deletefile(self, filename, isdir):
        if filename in self.remotelistcache[self.curdir]:
            print "* Removing", filename.encode('utf8')
            if isdir:
                self.ftp.rmd(filename)
            else:
                self.ftp.delete(filename)
            self.remotelistcache[self.curdir].remove(filename)

    def checkdeleted(self, files, dirname, removeAll=False):
        if dirname in self.checkeddirs:
            return
        self.checkeddirs.add(dirname)
        rdir = self.remotedir(dirname)
        #print "** Checking", rdir
        dirinfo = self.getdirinfo(rdir)
        removedirs = []

        def remove(filename, fileinfo, isdir):
            self.deletefile( fileinfo.key, isdir )
            del dirinfo[filename]
            self.mustsavedirinfo = True

        for filename, fileinfo in dirinfo.items():
            fullpath = os.path.join(dirname, filename)
            if removeAll or not fullpath in files:
                if fileinfo.isdir:
                    removedirs.append(fullpath)
                else:
                    remove(filename, fileinfo, False)
        if removeAll:
            self.deletefile(self.dirinfoname, False)
            del self.dirinfos[rdir]
        for fullpath in removedirs:
            self.checkdeleted(files, fullpath, True)
            filename = os.path.basename(fullpath)
            fileinfo = dirinfo[os.path.basename(fullpath)]
            self.changedir(rdir)
            remove(filename, fileinfo, True)

    def copyfiles(self, files):
        for filepath in files:
            parent = os.path.dirname(filepath)
            self.checkdeleted(files, parent)
            if os.path.isdir(filepath):
                self.savedir(filepath)
            else:
                self.copyfile(filepath)
        if self.mustsavedirinfo:
            self.savedirinfo(self.curdir)

    def sync(self, dirname, repo):
        self.repo = '/' + self.bkpdirname + '/' + repo
        files = self.filelist(dirname)
        #if len(files) == 0:
        #    self.checkdeleted(files, '', True)
        #else:
        self.copyfiles(files)

    def close(self):
        if self.mustsavedirinfo:
            self.savedirinfo(self.curdir)
        self.ftp.quit()

sync = FtpSync(getpass.getpass())
try:
    # o path deve estar em unicode
    sync.sync(u'.', u'python')
except KeyboardInterrupt:
    sync.close()
