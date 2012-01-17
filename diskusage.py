#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 11-jun-2012
import os
import sys

SIZE_G = 1024*1024*1024
SIZE_M = 1024*1024
SIZE_K = 1024

def formatBytes(size):
    if size > SIZE_G:
        return "%0.1fGB" % (float(size) / SIZE_G)
    if size > SIZE_M:
        return str(int(size / SIZE_M)) + "MB"
    if size > SIZE_K:
        return str(int(size / SIZE_K)) + "KB"
    return str(size) + "B"

def dirsort(dir1, dir2):
    if dir1.size > dir2.size:
        return 1
    if dir1.size < dir2.size:
        return -1
    return 0

class Dir(object):
    def __init__(self, path):
        self.path = path
        self.dirs = []
        self.size = 0

    def show(self):
        print self.path.encode('latin1'), "." * (100 - len(self.path)), formatBytes(self.size)

class DiskUsage(object):
    def filelist(self):
        # o path deve ser unicode
        self.dir = self.filelistrec(self.basepath)
        return self.dir

    def filelistrec(self, dirpath):
        d = Dir(dirpath)
        dirs = []
        try:
            for fname in os.listdir(dirpath):
                if fname in ['.', '..']:
                    continue
                filepath = os.path.join(dirpath, fname)
                if os.path.isdir(filepath):
                    dirs.append(filepath)
                else:
                    d.size += os.path.getsize(filepath)
        except Exception as e:
            print str(e)
            pass
        newdir = Dir(os.path.join(dirpath, '.'))
        newdir.size = d.size
        d.dirs.append(newdir)
        for filepath in dirs:
            newdir = self.filelistrec(filepath)
            d.dirs.append(newdir)
            d.size += newdir.size
        return d

    def analise(self, dirname):
        self.basepath = os.path.normpath(os.path.abspath(dirname)).decode(sys.getfilesystemencoding())
        self.filelist()

class DirNav(object):
    def __init__(self, dir):
        self.dir = dir
        self.stack = []

    def run(self):
        while True:
            print
            self.show(self.dir)
            while True:
                sop = raw_input("Option: ").lower().strip()
                if sop == '':
                    continue
                if sop == 'b' or sop == 'u':
                    if len(self.stack) > 0:
                        self.dir = self.stack.pop()
                        break
                    else:
                        print "No more directories on stack."
                elif sop == 'q' or sop == 'quit' or sop == 'exit':
                    return
                else:
                    try:
                        parent = self.dir
                        self.dir = self.dirs[int(sop)]
                        self.stack.append(parent)
                        break
                    except:
                        print "Invalid Option."

    def show(self, dir = None):
        if dir is None:
            dir = self.dir
        dir.show()
        print
        self.dirs = sorted(dir.dirs, dirsort, reverse=True)
        i = 0
        for d in self.dirs:
            print "%2d" % i,
            i += 1
            d.show()

if len(sys.argv) < 2:
    print "Use:", sys.argv[0], "<dir>"
    sys.exit(1)

du = DiskUsage()
du.analise(sys.argv[1])
nav = DirNav(du.dir)
nav.run()
