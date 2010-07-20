#!/bin/sh

pot=monitors.pot
newpot=/tmp/monitors.pot.new

xgettext --no-location -s --no-wrap --output=$newpot ../*.py

#check for changes
if ! diff --changed-group-format="%<" --new-group-format=%L --old-group-format=%L \
	--unchanged-group-format=  $pot $newpot | grep -qve '^"POT-Creation-Date:'; then
	rm $newpot
	echo "no changes in ${pot}."
	exit
fi

mv $newpot $pot

pofiles=`ls | grep -e \.po$`

for f in $pofiles; do
	msgmerge --no-location -v -s --no-wrap -U "${f}" $pot
done
