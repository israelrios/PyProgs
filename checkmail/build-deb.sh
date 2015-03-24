#!/bin/bash

curdir=`pwd`
if [ "$curdir" == "/" ]; then
	echo "Don't run this script in /"
	exit
fi

basedir="deb/usr/share"

rm -rf $optdir

dir="$basedir/iexpresso"
mkdir -p $dir
cp -a {monitors,expresso,checkmail,iexpresso,imap4utf7,monutil,imapcheckmail,requestprocessor}.py $dir
cp -a {mail-read.png,mail-unread.{png,svg}} $dir
cp -a iexpresso-auto.desktop $dir
cp -a dovecot*.conf $dir
#gmail checker
cp -a gmail*.{py,png,desktop} $dir

#refresh po's
#cd po
#./refresh_po.sh
#cd ..

#build mo's
localedir="${basedir}/locale"
if [ -d $localedir ]; then
	rm -rf "$localedir"
fi

appmo="monitors.mo"
pofiles=`ls po | grep -e \.po$`
for f in $pofiles; do
	langdir="${localedir}/${f%.po}/LC_MESSAGES"
	if [ ! -d $langdir ]; then
		mkdir -p $langdir
	fi
	msgfmt --output-file="${langdir}/$appmo" "po/$f"
done

#update version
version=`python -c "import monitors; print monitors.version"`
control=`cat deb/DEBIAN/control.in`
echo "${control//'%%version%%'/${version}}" > deb/DEBIAN/control

#build deb
fakeroot dpkg-deb -b deb ..

rm -rf $dir

#upload
if [ "$1" == '--upload' ]; then
	debrepo=../debrepo
	reprepro -b $debrepo/deb/ remove stable iexpresso
	reprepro -b $debrepo/deb/ includedeb stable "../iexpresso_${version}_all.deb" && \
		${HOME}/dev/google_appengine/appcfg.py update $debrepo
fi
