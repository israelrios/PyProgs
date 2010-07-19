#!/bin/sh

pot=monitors.pot

xgettext -s --no-wrap --output=$pot ../*.py

pofiles=`ls | grep -e \.po$`

for f in $pofiles; do
	msgmerge -v -s --no-wrap -U "${f}" $pot
done
