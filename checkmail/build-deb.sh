#!/bin/bash

curdir=`pwd`
if [ "$curdir" == "/" ]; then
	echo "Don't run this script in /"
	exit
fi

pack="iexpresso.deb"

if [ -a $pack ]; then
	rm $pack
fi

basedir="deb/usr/share"

rm -rf $optdir

dir="$basedir/iexpresso"
mkdir -p $dir
cp -a {monitors,expresso,checkmail,iexpresso,imap4utf7,monutil}.py $dir
cp -a {mail-read.png,mail-unread.{png,svg}} $dir
cp iexpresso-auto.desktop $dir
cp dovecot.conf $dir

fakeroot dpkg-deb -b deb ..

rm -rf $dir
