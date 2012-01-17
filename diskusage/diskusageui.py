#!/usr/bin/python
# -*- coding: utf-8 -*-
# Autor: Israel Rios
# Created: 17-jan-2012

from PyQt4 import QtCore as qt, QtGui as qtgui
import mainwindow
import diskusage

def createTreeItem(parent, dir, parentpath = None):
    path = dir.path
    if not parentpath is None:
        path = path[len(parentpath)+1:]
    item = qtgui.QTreeWidgetItem(parent, [path, diskusage.formatBytes(dir.size)])
    dirs = sorted(dir.dirs, diskusage.dirsort, reverse=True)
    for d in dirs:
        createTreeItem(item, d, dir.path)
    return item

class RunThread(qt.QThread):
    def __init__(self, dir):
        qt.QThread.__init__(self)
        self.dir = dir
        self.du = diskusage.DiskUsage()

    def run(self):
        self.du.analise(self.dir)

    def stop(self):
        self.du.stop()

class MainWindow(qtgui.QMainWindow):
    def __init__(self):
        qtgui.QMainWindow.__init__(self)
        self.ui = mainwindow.Ui_MainWindow()
        self.ui.setupUi(self)
        self.ui.tree.setColumnWidth(0, 500)

    def execute(self):
        sdir = unicode(qtgui.QFileDialog.getExistingDirectory(self, "Directory Selection"))
        if sdir != '':
            self.ui.tree.clear()

            self.progress = qtgui.QProgressDialog(self, qt.Qt.WindowTitleHint)
            self.progress.setLabelText('Computing directories sizes ...')
            self.progress.setWindowModality(qt.Qt.WindowModal)
            self.progress.setMaximum(0)
            self.progress.setMinimum(0)
            self.progress.setWindowTitle('Progress')
            self.progress.forceShow()
            qt.QObject.connect(self.progress, qt.SIGNAL("canceled()"), self.cancel)

            self.thread = RunThread(sdir)
            qt.QObject.connect(self.thread, qt.SIGNAL("finished()"), self.completed, qt.Qt.QueuedConnection)
            self.thread.start()

    def cancel(self):
        self.thread.stop()
        self.progress = None

    def completed(self):
        if self.thread.du.stopped():
            return
        item = createTreeItem(None, self.thread.du.dir)
        self.progress.close()
        self.progress = None
        self.thread = None
        self.ui.tree.addTopLevelItem(item)
        item.setExpanded(True)

if __name__ == "__main__":
    import sys
    app = qtgui.QApplication(sys.argv)
    mainWindow = MainWindow()
    mainWindow.show()
    sys.exit(app.exec_())

