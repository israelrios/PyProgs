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
import sys
import urllib
import fnmatch

class ProgressBar(object):
    def __init__(self, limit):
        self.limit = limit
        self.pos = 0
        self.oldpb = None
        self.make()
        self.show()

    def make(self):
        if self.limit == 0:
            progress = 1
        else:
            progress = (float(self.pos) / self.limit)
        size = 77 # tamanho da barra
        bar = "#" * int(size * progress)
        self.pb = "[" + bar + " " * (size - len(bar)) + "] " + str(int(progress * 100)) + "%"

    def show(self):
        if self.oldpb != self.pb:
            print self.pb, "\r",
            sys.stdout.flush()
            self.oldpb = self.pb

    def callback(self, data):
        self.pos += len(data)
        self.make()
        self.show()

    def clear(self):
        print ' ' * len(self.oldpb), "\r",
        sys.stdout.flush()

class FileInfo(object):
    def __init__(self, key=None, date=None):
        self.key = key
        self.date = date

class DirInfo(dict):
    def __init__(self, version = 1, generated = time.time()):
        self.version = version
        self.generated = generated
        self.updcount = 0

    def parse(self, lines):
        if len(lines) < 2:
            return False
        self.version = int(lines[0])
        self.generated = time.strptime(lines[1])
        self.updcount = 0
        for line in lines[2:]:
            if line == 'ok':
                return True
            (filename, key, date) = line.split(';')
            self[filename] = FileInfo(key, date)
        return False

    def refcount(self, filekey):
        count = 0
        for filepath, fileinfo in self.items():
            if fileinfo.key == filekey:
                count += 1
        return count

    def format(self):
        # linha 0: versão
        # linha 1: data de geração
        lines = ['1', time.ctime()]
        for filename, fileinfo in self.items():
            lines.append(';'.join([filename, fileinfo.key, fileinfo.date]))
        lines.append('ok')
        return '\n'.join(lines).encode('utf8')


class FtpSync(object):
    bkpdirname = 'bkp_dir'
    dirinfoname = "dirinfo__.bkp"
    def __init__(self, server, username, passwd):
        object.__init__(self)
        self.ftp = ftplib.FTP(server, username, passwd)
        self.curdir = '/'
        self.server = server
        self.username = username
        self.remotelistcache = {}
        self.dirinfos = {}
        self.loadlocaldirinfos()

    def changedir(self, remotedir):
        if remotedir != '/':
            remotedir = remotedir.rstrip('/')
        if remotedir != self.curdir:
            self.savedirinfo(self.curdir)
            print "* Changing dir", remotedir
            self.ftp.cwd(remotedir)
            self.curdir = remotedir

    def isexcluded(self, filepath):
        """ Returns True when some ignored pattern matches filepath. """
        if os.path.basename(filepath) == self.dirinfoname:
            return True
        for pat in self.excludes:
            if fnmatch.fnmatch(filepath, pat):
                return True
        return False

    def filelist(self):
        lst = []
        fsenc = sys.getfilesystemencoding()
        self.filelistrec(lst, "", fsenc)
        return lst

    def filelistrec(self, lst, dirpath, fsenc):
        dirs = []
        files = []
        for fname in os.listdir(os.path.join(self.basepath, dirpath)):
            filepath = os.path.join(dirpath, fname.decode(fsenc))
            if not self.isexcluded(filepath):
                if os.path.isdir(os.path.join(self.basepath, filepath)):
                    dirs.append(filepath)
                else:
                    files.append(filepath)
        lst.extend(sorted(files))
        for filepath in dirs:
            self.filelistrec(lst, filepath, fsenc)

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
        dirname = "/".join([urllib.quote_plus(name.encode('latin1')) for name in dirname.split('/')])
        if dirname != self.curdir:
            self.mkdirs(dirname)
            self.changedir(dirname)
        return dirname

    def getdirinfo(self, remotedir):
        if remotedir in self.dirinfos:
            return self.dirinfos[remotedir]
        dirinfo = None
        if self.dirinfoname in self.remotelist(remotedir):
            self.changedir(remotedir)
            lines = []
            def newline(line):
                lines.append(line.decode('utf8'))
            print "* Reading", self.dirinfoname
            self.ftp.retrlines('RETR ' + self.dirinfoname, newline)
            dirinfo = DirInfo()
            if not dirinfo.parse(lines):
                dirinfo = None
        if remotedir in self.localdirinfos:
            localdirinfo = self.localdirinfos[remotedir]
            if dirinfo is None or localdirinfo.generated > dirinfo.generated:
                dirinfo = localdirinfo
        if dirinfo is None:
            dirinfo = DirInfo()
        self.dirinfos[remotedir] = dirinfo
        return dirinfo

    def savedirinfo(self, remotedir):
        if not remotedir in self.dirinfos:
            return
        dirinfo = self.dirinfos[remotedir]
        if dirinfo.updcount == 0:
            return
        self.changedir(remotedir)
        self.store(self.dirinfoname, dirinfo.format(), binary=False)
        dirinfo.updcount = 0
        if remotedir in self.localdirinfos:
            del self.localdirinfos[remotedir]
            self.savelocaldirinfos()

    def dirinfoupdated(self):
        dirinfo = self.getdirinfo(self.curdir)
        dirinfo.updcount += 1
        self.localdirinfos[self.curdir] = dirinfo
        self.savelocaldirinfos()
        if dirinfo.updcount >= 10:
            self.savedirinfo(self.curdir)

    def makelocaldirinfopath(self):
        return os.path.join(userdir, 'ftpbkp', self.server + "@" + self.username + ".dirinfo")

    def savelocaldirinfos(self):
        lines = []
        for rdir, dirinfo in self.localdirinfos.items():
            lines.append(rdir.encode('utf8'))
            lines.append(dirinfo.format())
            lines.append('')
            lines.append('')
        filepath = self.makelocaldirinfopath()
        appdir = os.path.dirname(filepath)
        if not os.path.exists(appdir):
            os.makedirs(appdir)
        with open(filepath, "w") as f:
            f.write("\n".join(lines))

    def loadlocaldirinfos(self):
        filepath = self.makelocaldirinfopath()
        self.localdirinfos = {}
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                text = f.read().decode('utf8').rstrip()
            if text != '':
                for localdirinfo in text.split('\n\n'):
                    lines = localdirinfo.strip().split('\n')
                    dirinfo = DirInfo()
                    if dirinfo.parse(lines[1:]):
                        dirinfo.updcount = 1 # pra forçar a salvar
                        self.localdirinfos[lines[0]] = dirinfo

    def copyfile(self, filepath):
        rdir = self.baserdir
        dirinfo = self.getdirinfo(rdir)
        print filepath.encode('utf8')
        fullpath = os.path.join(self.basepath, filepath)
        with open(fullpath, 'rb') as f:
            data = f.read()
        # key computation
        key = hashlib.sha1()
        key.update(data)
        filekey = key.hexdigest()

        if filepath in dirinfo:
            oldkey = dirinfo[filepath].key
            if oldkey == filekey and filekey in self.remotelist(rdir): # same key?
                return
            self.deleterefcount(filepath)

        if dirinfo.refcount(filekey) == 0 or not filekey in self.remotelist(rdir):
            data = zlib.compress(data)
            self.store(filekey, data)
        # dirinfo
        filedate = time.ctime(os.path.getmtime(fullpath))
        dirinfo[filepath] = FileInfo(filekey, filedate)
        self.dirinfoupdated()

    def store(self, filename, data, binary=True):
        print "* Storing", filename.encode('utf8')
        pb = ProgressBar(len(data)-1)
        try:
            if binary:
                self.ftp.storbinary('STOR ' + filename, cStringIO.StringIO(data), callback=pb.callback)
            else:
                self.ftp.storlines('STOR ' + filename, cStringIO.StringIO(data), callback=pb.callback)
        finally:
            pb.clear()
        if self.curdir in self.remotelistcache:
            self.remotelistcache[self.curdir].append(filename)

    def deletefile(self, filename, isdir):
        if filename in self.remotelist(self.curdir):
            print "* Removing", filename.encode('utf8')
            if isdir:
                self.ftp.rmd(filename)
            else:
                self.ftp.delete(filename)
            self.remotelistcache[self.curdir].remove(filename)

    def deleterefcount(self, filepath):
        dirinfo = self.getdirinfo(self.curdir)
        fileinfo = dirinfo[filepath]
        if dirinfo.refcount(fileinfo.key) <= 1:
            self.deletefile( fileinfo.key, False )
        del dirinfo[filepath]
        self.dirinfoupdated()

    def checkdeleted(self, files, dirname, removeAll=False):
        rdir = self.remotedir(dirname)
        #print "** Checking", rdir
        dirinfo = self.getdirinfo(rdir)

        for filepath, fileinfo in dirinfo.items():
            if removeAll or not filepath in files:
                self.deleterefcount(filepath)

        if removeAll:
            self.deletefile(self.dirinfoname, False)
            if rdir in self.dirinfos:
                del self.dirinfos[rdir]

    def copyfiles(self, files):
        for filepath in files:
            self.copyfile(filepath)

    def sync(self, dirname):
        self.basepath = os.path.normpath(os.path.abspath(dirname))
        print "** Backing up", self.basepath
        with open(os.path.join(self.basepath,'ftpbkp.conf'), 'r') as f:
            conf = f.read().decode('utf8').strip().split('\n')
        self.repo = '/' + self.bkpdirname + '/' + conf[0].decode('utf8')
        # get ignored patterns
        self.excludes = ["*~"]
        for pattern in conf[1:]:
            if pattern.startswith('E'):
                self.excludes.append(pattern[1:])

        files = self.filelist()
        self.baserdir = self.remotedir('')
        self.copyfiles(files)
        self.checkdeleted(files, '')
        self.savedirinfo(self.curdir)

        print "** Done"

    def close(self):
        try:
            self.savedirinfo(self.curdir)
            self.ftp.quit()
        except:
            self.ftp.close()

if len(sys.argv) < 2:
    print "Use:", sys.argv[0], "<dir>"
    sys.exit(1)

userdir = os.getenv('USERPROFILE') or os.getenv('HOME')
with open(os.path.join(userdir, '.ftpbkp.conf'), 'r') as f:
    conf = f.read().strip().split('\n')
if len(conf) == 2:
    conf.append(getpass.getpass())
sync = FtpSync(conf[0], conf[1], conf[2])
try:
    # o path deve estar em unicode
    sync.sync(sys.argv[1])
except KeyboardInterrupt:
    sync.close()
