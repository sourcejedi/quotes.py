#!/usr/bin/env python
# -*- coding: UTF-8

# quotes.py
#
# Tool for converting to and/or checking "smart quotes" in long HTML documents.
#
# <https://github.com/sourcejedi/quotes.py>

# This script was originally developed using python3;
# it should convert back very nicely using 2to3
# (for best results, remove all use of unicode() and (object) first :).

import sys
import os
import glob
import optparse
import io
import htmlentitydefs

# TODO list:
#
# docs
# automated tests?
#
# Ideally, we should be able to turn off checking brackets, in case of false positives.
#
# We're silently clobbering files with a .tmp extension

# --strict-british
# --strict-american
# (like samequotes, but with a set starting quote type)

# NOT IMPLEMENTED:
#  Character encoding must be specified manually (if not UTF-8).
#  <q> tags will be ignored
#  <pre> will be treated as one big paragraph
#  <br> - even multiple successive line breaks 
#         will not be treated as a paragraph break
#
# We don't have any progress indicator, and we can take e.g. 30s to run on my EeePC.

opt = optparse.OptionParser(usage=
"""%prog [operations] [options] [FILES]

Check and/or convert to "smart quotes" in HTML.

If no operations are specified, --all is assumed.""")

opt.add_option('-m', '--modify',
	action="store_true", dest="modify",
	help="modify original file(s)")

opt.add_option('--encoding',
	dest="encoding", default="UTF-8")


opt_do = optparse.OptionGroup(opt, 'Operations')
opt_do.add_option('-a', '--all',
	action="store_true", dest="do_all")

opt_do.add_option('--apostrophe',
	action="store_true", dest="do_apostrophe",
	help="mark ambiguous quote/apostrophe at end of words")

opt_do.add_option('--mismatch',
	action="store_true", dest="do_mismatch",
	help="check for mismatched quotes and curly brackets")

opt_do.add_option('--spacing',
	action="store_true", dest="do_spacing",
	help="check for quote marks with odd spacing")

opt_do.add_option('--nesting',
	action="store_true", dest="do_nesting",
	help="check nested quotations")
opt.add_option_group(opt_do)


opt_conf = optparse.OptionGroup(opt, 'General options')
opt_conf.add_option('--ignore-straight-quotes',
	action="store_true", dest="ignore_straight_quotes",
	help="don't try to convert 'straight' quotation marks "
		"(this implies they will not be checked at all)")

opt_conf.add_option('--warning-mark',
	dest="WARN", default=u'#', metavar="MARK",
	help='warning marker used by most operations, default is "%default"')
opt.add_option_group(opt_conf)


opt_conf = optparse.OptionGroup(opt, 'Options for --apostrophe')
opt_conf.add_option('--skip-leading-apostrophes',
	action="store_true", dest="skip_leading_apostrophe",
	help="don't mark apostrophes at the start of words")

opt_conf.add_option('--mark', dest="MARK", default=u'*',
	help='marker for ambiguous apostrophes, default is "%default"')
opt.add_option_group(opt_conf)


opt_conf = optparse.OptionGroup(opt, 'Options for --nesting')
opt_conf.add_option('--allow-same-quotes',
	action="store_true", dest="allow_same_quotes",
	help="allow nested quotations which use "
		"the same style of quotation marks")

opt_conf.add_option('--max-depth',
	type="int", dest="max_depth", metavar="N", default=2,
	help="maximum depth of nested quotations/brackets, "
		"default value is %default")
opt.add_option_group(opt_conf)


# Now parse arguments
(options, args) = opt.parse_args()

ops = [option for option in options.__dict__ if option.startswith('do_')]

do_ops = [op for op in ops if getattr(options, op)]
if not do_ops:
	# default to --all
	options.do_all = True

if options.do_all:
	# --all enables every operation
	for op in ops:
		setattr(options, op, True)


# Ambiguities and warnings are marked
# with these characters in our output.
OUTPUT_MARK = unicode(options.MARK) # "*"
OUTPUT_WARN = unicode(options.WARN) # "#"


class Counters:
	def __init__(count):
		count.openq = 0
		count.closeq = 0

		count.leading_apostrophe = 0
		count.ambiguous_apostrophe = 0

		count.unmatched_q = 0
		count.unmatched = 0

		count.samequotes = 0
		count.too_deep = 0

		count.spaced_q = 0
		count.unspaced_q = 0

		count.straight_q = 0
		count.straight_q2 = 0

counters = Counters()


#
# <reusable>
#

#
# PARAGRAPH_ELEMENTS
#
# A list of the HTML elements which indicate a new paragraph.
# Mostly those which default to CSS display:block.
#
# Derived from HTML5, this is supposed to be all "flow content"
# that is not declared as "phrasing content"
# (which would default to display:inline).
#
# Table cells and list items are also included.
#
# python 2: left these as non-unicode strings for clarity; they're all ASCII anyway.
#
PARAGRAPH_ELEMENTS = [
	'p',
	
	'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
	'blockquote',
	'hr',

	# Table cells, table heading cells, list items
	'td', 'th', 'li',

	'html',
	'title',
	'body',
	'div',
	# <center> was an alias for <div align="center"> 
	'center',
	
	# HTML5
	'section', 'article',
	'aside',
	
	# At least force paragraph breaks around <pre>,
	# even if we don't handle the contents correctly.
	'pre',
]

#
# INVISIBLE_ELEMENTS
#
# List of elements whose content would not be displayed.
# (display:none)
#
INVISIBLE_ELEMENTS = ['script', 'style']


class XhtmlTokenizer(object):
	"""Gonzo xhtml tokenizer.
	
	Callbacks based on expat, except no attribute data,
	and text is delivered one character at a time.
	"""
	
	__slots__ = (
		# The XML token which is currently being read
		# from the input file.  It's safe for the
		# callbacks to clobber this, if they want.
		'xml_token',
	)
	
	def start_element(self, name):
		pass
	def end_element(self, name):
		pass
	def character_data(self, c):
		assert len(c) == 1
	def noncharacter_data(self):
		pass
	def end_file(self):
		pass
	
	def run(self, infile):
		self.xml_token = ''

		def read_char(count=1):
			c = infile.read(count)
			if not c:
				raise StopIteration()
			self.xml_token += c
			return c

		def read_tag(first_c):
			c = first_c
			
			end_tag = False
			if c == u'/':
				end_tag = True
				c = read_char()				
			
			name = u''
			while c.isalnum() or c == u':':
				name += c
				c = read_char()
			assert name
			
			while c != u'>':
				c = read_char()
			
			if end_tag:
				self.end_element(name)
			elif self.xml_token[-2] == u'/':
				self.empty_element(name)
			else:
				self.start_element(name)

		def read_noncharacter_data(end):
			while not self.xml_token.endswith(end):
				read_char()
			self.noncharacter_data()

		def read_cdata():
			def feed(c):
				self.xml_token = c
				self.character_data(c)
			
			c = read_char()
			while True:
				while c != u']':
					self.character_data(c)
					self.xml_token = ''
					c = read_char()
				
				c = read_char()
				if c != u']':
					feed(u']')
					feed(c)
					continue
				
				c = read_char()
				if c != u'>':
					feed(u']')
					feed(u']')
					feed(c)
				
				self.xml_token = u']]>'
				self.noncharacter_data()
				return

		def start_token(token):
			assert token.startswith(self.xml_token)
			read_char(len(token) - len(self.xml_token))
			assert token == self.xml_token

		c = read_char()
		while c:
			if c == u'<':
				c = read_char()
				
				if c == u'!':
					c = read_char()
					if c == u'-':
						c = read_char()
						assert c == u'-'
						read_noncharacter_data(u'-->')
					elif c == u'[':
						start_token(u'<![CDATA[')
						self.noncharacter_data()
						self.xml_token = u''
						
						read_cdata()
					else:
						start_token(u'<!DOCTYPE')
						read_noncharacter_data(u'>')
				elif c == u'?':
					read_noncharacter_data(u'?>')
				else:
					read_tag(c)
			elif c == u'&':
				while c != u';':
					c = read_char()
				
				if self.xml_token[1] == u'#':	
					if self.xml_token[2].lower() == u'x':
						c = int(self.xml_token[3:-1], 0x10)
					else:
						c = int(self.xml_token[2:-1])
					self.character_data(unichr(c))
				else:
					name = self.xml_token[1:-1]
					if name == 'apos':
						c = u"'"
					else:
						c = unichr(htmlentitydefs.name2codepoint[name])
					self.character_data(c)
			else:
				self.character_data(c)
			
			c = self.xml_token = infile.read(1)


def isbreakspace(c):
	# NBSP and thin NBSP (Unicode defines more types of spaces,
	#    but it seems only two type have non-breaking variants)
	nobreaks = u'\u00A0\u202F'
	return c.isspace() and c not in nobreaks


# Stack to keep track of the current "open" punctuation marks,
# with a _limited_ non-deterministic pop() used to handle
# apostrophes which might be close-quote characters

class PunctuationFrame(object):
	__slots__ = (
		'p',		# open-punctuation character
		'q',		# close-punctuation character
		'opened',
		'maybe_closed')
	
	def __init__(self, p, q, opened=1, maybe_closed=0):
		self.p = p
		self.q = q
		self.opened = opened
		self.maybe_closed = maybe_closed
	
	def __repr__(self):
		return 'PunctuationFrame' + \
		repr((self.p, self.q, self.opened, self.maybe_closed))

class PunctuationStack(object):
	# This stack is used for code/concept-sharing
	# It is not strongly encapsulated.
	# The underscore on ._frames is just a warning
	__slots__ = ('_frames')
	
	def __init__(self):
		self._frames = []
	
	def __nonzero__(self):
		return bool(self._frames)
	
	def top(self):
		return self._frames[-1]

	def open(self, p, q):
		if self._frames and self._frames[-1].p == p:
			self._frames[-1].opened += 1
		else:
			self._frames.append(PunctuationFrame(p, q))
	
	def close(self, q):
		if not self._frames:
			raise IndexError() # [].pop()
		if self._frames[-1].q != q:
			raise ValueError() # [].index(p)
		
		self._frames[-1].opened -= 1
		if self._frames[-1].maybe_closed > self._frames[-1].opened:
			self._frames[-1].maybe_closed = self._frames[-1].opened
		
		if self._frames[-1].opened <= 0:
			self._frames.pop()
	
	def maybe_close(self, q):
		if not self._frames:
			return
		if self._frames[-1].q != q:
			return
			
		if self._frames[-1].maybe_closed < self._frames[-1].opened:
			self._frames[-1].maybe_closed += 1
	
	def close_maybes(self):
		self._frames[-1].opened -= self._frames[-1].maybe_closed
		
		if self._frames[-1].opened <= 0:
			self._frames.pop()

#
# </reusable>
#


class TextChecker(XhtmlTokenizer):
	__slots__ = ()
	
	__slots__ += ('outfile', 'buf')
	def outfile_init(self, outfile):
		self.outfile = outfile
		
		# Output buffer.  Any number of non-text XML tokens.
		# Before this is written to the output file, we may
		# insert some sort of marker.
		self.buf = []
	
	def save_token(self):
		self.buf.append(self.xml_token)

	def flush_tokens(self):
		o = self.outfile
		for token in self.buf:
			o.write(token)
		o.write(self.xml_token)
		del self.buf[:]

	def output_mark(self, mark):
		# Write a marker to the file,
		# before any buffered output
		self.outfile.write(mark)

	__slots__ += ('punct',)
	def punctuation_init(self):
		self.punct = PunctuationStack()

	def punctuation_open(self, pq):
		(p, q) = pq
		self.punct.open(p, q)
		
		samecount = self.punct.top().opened - self.punct.top().maybe_closed
		if samecount > 1:
			if options.do_nesting and not options.allow_same_quotes:
				self.output_mark(OUTPUT_WARN)
			counters.samequotes += 1
	
		d = sum([s.opened - s.maybe_closed for s in self.punct._frames])
		if d > options.max_depth:
			if options.do_nesting:
				self.output_mark(OUTPUT_WARN + u'[' + unicode(d) + u']')
			counters.too_deep += 1

	def punctuation_close(self, q):
		try:
			self.punct.close(q)
		except IndexError:
			# Punctuation stack was empty
			if q == u"’":
				counters.unmatched_q += 1
			else:
				counters.unmatched += 1
			
			if options.do_mismatch:
				self.output_mark(OUTPUT_WARN)
		except ValueError:
			# q did not match the top of the punctuation stack
			if len(self.punct._frames) >= 2 and q == self.punct._frames[-2].q and \
			   self.punct.top().maybe_closed == self.punct.top().opened:
				# Looks like the apostrophes we noted might have been close-quotes
				if options.do_apostrophe:
					self.output_mark(' ' + OUTPUT_MARK * self.punct.top().maybe_closed)
				# Pop all the apostrophes 
				self.punct.close_maybes()
				# Now we can close q without any problem
				self.punct.close(q)
			else:
				if options.do_mismatch:
					self.output_mark(OUTPUT_WARN + u'[' + self.punct.top().p + u']')
				# No attempt at recovery here. We may
				# generate some confusing-looking errors
				# until we get to the next paragraph,
				# though they're still possible to understand
				# if you know what we're doing.
				if q == u"’" or self.punct.top().p == u"‘":
					counters.unmatched_q += 1
				else:
					counters.unmatched += 1
				return

	def punctuation_maybe_close(self, q):
		if options.do_apostrophe:
			self.output_mark(OUTPUT_MARK)
		
		self.punct.maybe_close(q)

	def punctuation_endpara(self):
		if self.punct and self.punct.top().maybe_closed > 0:
			# Looks like some of the apostrophes we noted might have been close-quotes
			if options.do_apostrophe:
				self.output_mark(u' ' + OUTPUT_MARK * self.punct.top().maybe_closed)
			# So let's close the same number of open-quotes
			self.punct.close_maybes()

		if self.punct:
			if options.do_mismatch:
				self.output_mark(u' ' + OUTPUT_WARN + u'[')
				for frame in self.punct._frames:
					self.output_mark(frame.p)
					
					# This may cause some errors to be counted twice
					if frame.p == u"‘":
						counters.unmatched_q += 1
					else:
						counters.unmatched += 1
				self.output_mark(u']')
			self.punct._frames = []
	
	__slots__ += ('history', 'hidden_element')
	def __init__(self, outfile):
		self.outfile_init(outfile)
		self.punctuation_init()

		# An input window of three "characters".
		# These are non-space characters from text nodes,
		# " " for a run of whitespace characters, or
		# "\n" for a paragraph break.
		#
		# We can insert a marker after the middle character
		# using output_mark()
		self.history = [u"\n", u"\n", u"\n"]

		self.hidden_element = []


	def __character(self, next):
		# At this point, "token" contains the representation of
		# the character "c", and may be modified;
		# output marks will appear just _before_ the character "c"

		(prev, cur) = (self.history[-2], self.history[-1])

		if not options.ignore_straight_quotes:
			if next == u"'":
				counters.straight_q += 1
				if isbreakspace(cur):
					# Could be open-quote OR leading apostrophe.
					# We assume open-quote.
					# If we get it wrong, it should get flagged as a quote mismatch error
					#  - unless there is an ambiguous trailing apostrophe - which is what
					# the ambiguity markers are there for.
					next = u"‘"
				else:
					next = u"’"
				self.xml_token = next
				
			elif next == u'"':
				counters.straight_q2 += 1
				if isbreakspace(cur):
					next = u'“'
				else:
					next = u'”'
				self.xml_token = next

			# Done rewriting; update history
			del self.history[0]
			self.history.append(next)
		
		# TODO: make optional, in case of non-standard usage?
		if cur == u'(':
			self.punctuation_open(u'()')
		elif cur == u')':
			self.punctuation_close(u')')

		elif cur == u'“':
			if prev.isalnum():
				counters.unspaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			if isbreakspace(next):
				counters.spaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			self.punctuation_open(u'“”')
		elif cur == u'”':
			if isbreakspace(prev):
				counters.spaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			if next.isalnum():
				counters.unspaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			self.punctuation_close(u'”')

		# Open quote
		elif cur == u"‘":
			counters.openq += 1
			if prev.isalnum():
				counters.unspaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			if isbreakspace(next):
				counters.spaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			self.punctuation_open(u"‘’")

		elif cur == u"’":
			if prev.isalnum():
				if next.isalpha():
					# Internal, must be apostrophe
					pass
				else:
					# Ambiguous - could be end-of-word apostrophe OR closing quote
					counters.ambiguous_apostrophe += 1
					self.punctuation_maybe_close(u"’")
			else:
				if next.isalnum():
					# Should be a start-of-word apostrophe - 
					# but there's a possibility it's a wrongly-angled opening quote,
					# and there's usually not too many of these to check.
					counters.leading_apostrophe += 1
					if options.do_apostrophe and \
					   not options.skip_leading_apostrophe:
						self.output_mark(OUTPUT_MARK)
				else:
					if isbreakspace(prev):
						counters.spaced_q += 1
						if options.do_spacing:				
							self.output_mark(OUTPUT_WARN)
					# Not attached to word - must be a closing quote
					counters.closeq += 1
					self.punctuation_close(u"’")

	def character_data(self, c):	
		if not self.hidden_element:
			# All whitespace characters are treated the same
			# (apart from NBSP)
			if isbreakspace(c):
				c = u' '
			self.__character(c)
		self.flush_tokens()

	def __paragraph_break(self):
		self.__character(u'\n')
		self.punctuation_endpara()

	def start_element(self, name, *_):
		if name in INVISIBLE_ELEMENTS:
			self.hidden_element.append(name)
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()
		self.save_token()

	def end_element(self, name):
		if name in INVISIBLE_ELEMENTS:
			self.hidden_element.pop()
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()
		self.save_token()

	def empty_element(self, name):
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()
		self.save_token()
	
	def noncharacter_data(self):
		self.save_token()

	def end_file(self):
		self.punctuation_endpara()
		self.flush_tokens()


infile = sys.stdin
outfile = sys.stdout

# python2: fallback to get unicode stdin/stdout
# (twice as slow... though at least it respects --encoding, unlike what'll happen with python3)
if hasattr(infile.read(0), 'decode'):
	import codecs
	infile = codecs.getreader(options.encoding)(infile)
	outfile = codecs.getwriter(options.encoding)(outfile, errors='xmlcharrefreplace')

#class NullWriter:
#	def write(self, d):
#		pass
#	def flush(self):
#		pass
#	def close(self):
#		pass
#outfile = NullWriter()

if not args:
	if options.modify:
		print("--modify requires at least one filename")
		sys.exit(1)
	
	TextChecker(outfile).run(infile)
else:
	if os.name != 'posix':
		filenames = []
		for filename in args:
			filenames += glob.glob(filename)
		args = filenames

	for filename in args:
		infile = io.open(filename, 'r', encoding=options.encoding, newline='\n')
		if options.modify:
			outfile = io.open(filename+".tmp", 'w', encoding=options.encoding, errors='xmlcharrefreplace', newline='\n')
		
		TextChecker(outfile).run(infile)
		
		if options.modify:
			os.rename(filename+".tmp", filename)
			outfile.close()
		
		infile.close()

if not options.modify:
	outfile.flush()

report = sys.stderr
report.write("\nSingle quotes")
report.write("\n                    open quotes: " + str(counters.openq))
report.write("\n       unambiguous close quotes: " + str(counters.closeq))
report.write("\n")

report.write("\nApostrophes")
report.write("\n    apostrophe at start of word: " + str(counters.leading_apostrophe))
report.write("\n    ambiguous close-quote /")
report.write("\n      apostrophe at end of word: " + str(counters.ambiguous_apostrophe))
report.write("\n")

report.write("\nUnmatched quotes and brackets")
report.write("\n   single quotes (conservative): " + str(counters.unmatched_q))
report.write("\n   double quotes and brackets  : " + str(counters.unmatched))
report.write("\n")

report.write("\nNested quotations")
report.write("\n          nested " + str(options.max_depth + 1) +
                                 " deep or more: " + str(counters.too_deep))
report.write("\n      with same style of quotes: " + str(counters.samequotes))
report.write("\n")

# TODO this is documentation:
#  - check cases with no spaces, which might have been mis-handled
#  - this will also happen to flag up:
#    - extra spaces from OCR, which can often cause quotes to go in the wrong direction
#    - absence of NBSP in adjacent nested quotation marks
#    - absence of NBSP around en dash just inside quotation mark
#    - as above, for spaced out elipsis
#    (and any similar unsual typographic features)
# 
# TODO need to document NBSP specifically, because the distinction is technical and not obvious to the eye

report.write("\nQuote spacing")
report.write("\n              unexpected spaces: " + str(counters.spaced_q))
report.write("\n                 missing spaces: " + str(counters.unspaced_q))
report.write("\n")

# TODO document as defaulting to open-quotes (with user free to search+replace all)
report.write("\nStraight quote characters")
report.write("\n         straight single quotes: " + str(counters.straight_q))
report.write("\n         straight double quotes: " + str(counters.straight_q2))
report.write("\n")
