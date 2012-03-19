#!/usr/bin/python

# ssterm - simple serial-port terminal
# Version 1.3 - March 2012
# Written by Vanya A. Sergeev - <vsergeev@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
import sys
import os
import termios
import getopt
import select
import re

# Default TTY and Formatting Options
TTY_Options = {'baudrate': 9600, 'databits': 8, 'stopbits': 1, 'parity': "none", 'flowcontrol': "none"}
Format_Options = {'hexmode': False, 'txnl': "raw", 'rxnl': "lf", 'hexnl': False, 'echo': False}
Console_Newline = os.linesep

# ssterm Quit Escape Character, Ctrl-[ = 0x1B
Quit_Escape_Character = 0x1B

# Valid newline substitution types
Valid_RX_Newline_Type = ["raw", "cr", "lf", "crlf", "crorlf"]
Valid_TX_Newline_Type = ["raw", "none", "cr", "lf", "crlf"]

# Read buffer size
READ_BUFF_SIZE = 1024

# Number of columns in hex mode
Hexmode_Columns = 32


###########################################################################
### TTY Helper Functions
###########################################################################

def serial_open(devpath):
	# Open the tty device
	try:
		tty_fd = os.open(devpath, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK);
	except OSError, err:
		sys.stderr.write("Error opening serial port: %s\n" % str(err))
		return -1

	# Get the current tty options
	# Format: [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
	try:
		tty_attr = termios.tcgetattr(tty_fd)
	except termios.TermiosError, err:
		sys.stderr.write("Error getting serial port options: %s\n" % str(err))
		return -1

	# Look up the termios baudrate and set it in the attributes structure
	termios_baudrates = {50: termios.B50, 75: termios.B75, 110: termios.B110, 134: termios.B134, 150: termios.B150, 200: termios.B200, 300: termios.B300, 600: termios.B600, 1200: termios.B1200, 1800: termios.B1800, 2400: termios.B2400, 4800: termios.B4800, 9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400, 57600: termios.B57600, 115200: termios.B115200, 230400: termios.B230400}
	if (not TTY_Options['baudrate'] in termios_baudrates):
		sys.stderr.write("Invalid tty baudrate!\n")
		return -1
	tty_attr[4] = termios_baudrates[TTY_Options['baudrate']]
	tty_attr[5] = termios_baudrates[TTY_Options['baudrate']]

	# Reset attributes structure cflag -- tty_attribute[cflag]
	tty_attr[2] = 0

	# Look up and set the appropriate cflag bits in termios_options for a
	# given option, print error message and return -1 for an invalid option
	def termios_cflag_map_and_set(termios_options, option, errmsg):
		if (not option in termios_options):
			sys.stderr.write(errmsg)
			return -1
		tty_attr[2] |= termios_options[option]
		return 0

	# Look up the termios data bits and set it in the attributes structure
	termios_databits = {5: termios.CS5, 6: termios.CS6, 7: termios.CS7, 8: termios.CS8}
	if (termios_cflag_map_and_set(termios_databits, TTY_Options['databits'], "Invalid tty databits!\n") < 0):
		return -1

	# Look up the termios parity and set it in the attributes structure
	termios_parity = {"none": 0, "even": termios.PARENB, "odd": termios.PARENB | termios.PARODD}
	if (termios_cflag_map_and_set(termios_parity, TTY_Options['parity'], "Invalid tty parity!\n") < 0):
		return -1

	# Look up the termios stop bits and set it in the attributes structure
	termios_stopbits = {1: 0, 2: termios.CSTOPB}
	if (termios_cflag_map_and_set(termios_stopbits, TTY_Options['stopbits'], "Invalid tty stop bits!\n") < 0):
		return -1

	# Look up the termios flow control and set it in the attributes structure
	termios_flowcontrol = {"none": 0, "rtscts": termios.CRTSCTS, "xonxoff": 0}
	if (termios_cflag_map_and_set(termios_flowcontrol, TTY_Options['flowcontrol'], "Invalid tty flow control!\n") < 0):
		return -1

	# Enable the receiver
	tty_attr[2] |= (termios.CREAD | termios.CLOCAL);

	# Turn off signals generated for special characters, turn off canonical
	# mode so we can have raw input -- tty_attr[lflag]
	tty_attr[3] = 0

	# Turn off POSIX defined output processing and character mapping/delays
	# so we can have raw output -- tty_attr[oflag]
	tty_attr[1] = 0

	# Ignore break characters -- tty_attr[iflag]
	tty_attr[0] = termios.IGNBRK
	# Enable parity checking if we are using parity -- tty_attr[iflag]
	if (TTY_Options['parity'] != "none"):
		tty_attr[0] |= (termios.INPCK | termios.ISTRIP)
	# Enable XON/XOFF if we are using software flow control
	if (TTY_Options['flowcontrol'] == "xonxoff"):
		tty_attr[0] |= (termios.IXON | termios.IXOFF | termios.IXANY)

	# Set the new tty attributes
	try:
		termios.tcsetattr(tty_fd, termios.TCSANOW, tty_attr)
	except termios.TermiosError, err:
		sys.stderr.write("Error setting serial port options: %s\n" % str(err))
		return -1

	# Return the tty_fd
	return tty_fd

def serial_close(fd):
	try:
		os.close(fd)
		return 0
	except:
		return -1

def fd_read(fd, n):
	try:
		return (0, os.read(fd, n))
	except OSError, err:
		# Check if non-blocking read returned 0
		if (err.errno == 11): return (0, None)
		else: return (-1, str(err))

def fd_write(fd, data):
	try:
		return os.write(fd, data)
	except OSError, err:
		return -1

###########################################################################
### Read/Write Loop
###########################################################################

# Global variables for console read/write loop
serial_fd = None
stdin_fd = None
txnl_sub = None
rxnl_match = None
stdout_nl_match_save = ''
stdout_cursor_x = 0

def console_init():
	global stdin_fd, txnl_sub, rxnl_match

	stdin_fd = sys.stdin.fileno()

	# Get the current stdin tty options
	# Format: [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
	try:
		stdin_attr = termios.tcgetattr(stdin_fd)
	except termios.TermiosError, err:
		sys.stderr.write("Error getting stdin tty options: %s\n" % str(err))
		return -1

	# Disable canonical input, so we can send characters without a
	# line feed, and disable echo -- stdin_attr[cflag]
	stdin_attr[3] &= ~(termios.ICANON | termios.ECHO | termios.ECHOE | termios.ISIG)
	# Turn off XON/XOFF interpretation so they pass through to the serial
	# port -- stdin_attr[iflag]
	stdin_attr[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
	# Enable echo if needed
	if (Format_Options['echo']): stdin_attr[3] |= termios.ECHO

	# Set the new stdin tty attributes
	try:
		termios.tcsetattr(stdin_fd, termios.TCSANOW, stdin_attr)
	except termios.TermiosError, err:
		sys.stderr.write("Error setting stdin tty options: %s\n" % str(err))
		return -1

	# Re-open stdout in unbuffered mode
	sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

	# Look up the appropriate substitution for our transmit newline option
	if Format_Options['txnl'] == "none": txnl_sub = ""
	elif Format_Options['txnl'] == "cr": txnl_sub = "\r"
	elif Format_Options['txnl'] == "crlf": txnl_sub = "\r\n"
	elif Format_Options['txnl'] == "lf": txnl_sub = "\n"
	# "raw" requires no substitution
	else: txnl_sub = None

	# Look up the appropriate matches for our receive newline option
	if Format_Options['rxnl'] == "cr": rxnl_match = "\r"
	elif Format_Options['rxnl'] == "lf": rxnl_match = "\n"
	elif Format_Options['rxnl'] == "crlf": rxnl_match = "\r\n"
	elif Format_Options['rxnl'] == "crorlf": rxnl_match = "\r|\n"
	# "raw" requires no match
	else: rxnl_match = None


def console_formatted_print(data):
	global stdout_nl_match_save, stdout_cursor_x

	if len(data) == 0:
		return

	# Perform receive newline substitutions if necessary
	if rxnl_match != None:
		# If we had a left-over newline character match from before
		if stdout_nl_match_save != '':
			data = stdout_nl_match_save + data
			stdout_nl_match_save = ''

		# Split by all newline matches
		data = re.split(rxnl_match, data)
		# Re-join with the console line separator
		data = reduce(lambda x, y: x + Console_Newline + y, data)

		# If the last character is a part of a match, save it for later
		if data[-1] == rxnl_match[0][0]:
			stdout_nl_match_save = data[-1]
			data = data[0:-1]

	# Convert to hex if we're in hex mode
	if Format_Options['hexmode']:
		for x in list(data):
			sys.stdout.write("%02X" % ord(x))
			stdout_cursor_x += 1
			# Pretty print into two columns
			if stdout_cursor_x == Hexmode_Columns/2:
				sys.stdout.write("  ")
			elif stdout_cursor_x == Hexmode_Columns:
				sys.stdout.write("\n")
				stdout_cursor_x = 0
			else:
				sys.stdout.write(" ")
			# Insert a newline if we encounter one and we're
			# interpreting them in hex mode
			if x == Console_Newline and Format_Options['hexnl']:
				sys.stdout.write(Console_Newline)
				stdout_cursor_x = 0
	# Normal print
	else:
		sys.stdout.write(data)


def console_read_write_loop():
	# Select between serial port and stdin file descriptors
	read_fds = [serial_fd, stdin_fd]
	while True:
		ready_read_fds, ready_write_fds, ready_excep_fds = select.select(read_fds, [], [])

		if stdin_fd in ready_read_fds:
			# Read a buffer from stdin
			retval, buff = fd_read(stdin_fd, READ_BUFF_SIZE)
			if retval < 0:
				sys.stderr.write("Error reading stdin: %s\n" % buff)
				break
			if len(buff) > 0:
				# Perform transmit newline subsitutions if necessary
				if txnl_sub != None:
					buff = map(lambda x: txnl_sub if x == Console_Newline else x, list(buff))
					buff = ''.join(buff)

				# If we detect the escape character, then quit
				if chr(Quit_Escape_Character) in buff:
					break

				# Write the buffer to the serial port
				retval = fd_write(serial_fd, buff)
				if retval < 0:
					sys.stderr.write("Error writing to serial port: %s\n" % buff)

		if serial_fd in ready_read_fds:
			# Read a buffer from stdin
			retval, buff = fd_read(serial_fd, READ_BUFF_SIZE)
			if retval < 0:
				sys.stderr.write("Error reading serial port: %s\n" % buff)
				break
			if len(buff) > 0:
				console_formatted_print(buff)


###########################################################################
### Command-Line Options Parsing
###########################################################################

def print_usage():
	print "Usage: %s <option(s)> <serial port>\n" % sys.argv[0]
	print "\
ssterm - simple serial-port terminal\n\
Written by Vanya A. Sergeev - <vsergeev@gmail.com>.\n\
\n\
 Serial Port Options:\n\
  -b, --baudrate <rate>         Specify the baudrate\n\
  -d, --databits <number>       Specify the number of data bits [5,6,7,8]\n\
  -p, --parity <type>           Specify the parity [none, odd, even]\n\
  -t, --stopbits <number>       Specify number of stop bits [1,2]\n\
  -f, --flow-control <type>     Specify the flow-control [none, rtscts, xonxoff]\n\
\n\
 Formatting Options:\n\
  --tx-nl <substitution>        Specify the transmit newline substitution\n\
                                 [raw, none, cr, lf, crlf]\n\
  --rx-nl <match>               Specify the receive newline combination\n\
                                 [raw, cr, lf, crlf, crorlf]\n\
  -e, --echo                    Turn on local character echo\n\
  -x, --hex                     Turn on hexadecimal representation mode\n\
  --hex-nl                      Turn on newlines in hexadecimal mode\n\
\n\
  -h, --help                    Display this usage/help\n\
  -v, --version                 Display the program's version\n\n"
	print "\
Quit Escape Character:          Ctrl-[\n\
\n\
Default Options:\n\
 baudrate: 9600 | databits: 8 | parity: none | stopbits: 1 | flow control: none\n\
 tx newline: raw | rx newline: lf | local echo: off | hexmode: off\n"

def print_version():
	print "ssterm version 1.3 - 03/19/2012"

def int_handled(x):
	try:
		return int(x)
	except:
		return False

# Parse options
try:
	options, args = getopt.getopt(sys.argv[1:], "b:d:p:t:f:exhv", ["baudrate=", "databits=", "parity=", "stopbits=", "flowcontrol=", "tx-nl=", "rx-nl=", "echo", "hex", "hex-nl", "color-nl", "help", "version"])
except getopt.GetoptError, err:
	print str(err), "\n"
	print_usage()
	sys.exit(-1)


# Update options containers
for opt_c, opt_arg in options:
	if opt_c in ("-b", "--baudrate"):
		TTY_Options['baudrate'] = int_handled(opt_arg)
		if (not TTY_Options['baudrate']):
			sys.stderr.write("Invalid tty baudrate!\n")
			sys.exit(-1)

	elif opt_c in ("-d", "--databits"):
		TTY_Options['databits'] = int_handled(opt_arg)
		if (not TTY_Options['databits']):
			sys.stderr.write("Invalid tty data bits!\n")
			sys.exit(-1)

	elif opt_c in ("-p", "--parity"):
		TTY_Options['parity'] = opt_arg

	elif opt_c in ("-t", "--stopbits"):
		TTY_Options['stopbits'] = int_handled(opt_arg)
		if (not TTY_Options['stopbits']):
			sys.stderr.write("Invalid tty stop bits!\n")
			sys.exit(-1)

	elif opt_c in ("-f", "--flowcontrol"):
		TTY_Options['flowcontrol'] = opt_arg

	elif opt_c in ("-e", "--echo"):
		Format_Options['echo'] = True

	elif opt_c in ("-x", "--hex"):
		Format_Options['hexmode'] = True

	elif opt_c == "--tx-nl":
		Format_Options['txnl'] = opt_arg
		if (not Format_Options['txnl'] in Valid_Newline_Type[0:-1]):
			sys.stderr.write("Invalid tx newline type!\n")
			print_usage()
			sys.exit(-1)

	elif opt_c == "--rx-nl":
		Format_Options['rxnl'] = opt_arg
		if (not Format_Options['rxnl'] in Valid_Newline_Type):
			sys.stderr.write("Invalid rx newline type!\n")
			print_usage()
			sys.exit(-1)

	elif opt_c == "--hex-nl":
		Format_Options['hexnl'] = True

	elif opt_c == "--color-nl":
		Format_Options['colornl'] = True

	elif opt_c in ("-h", "--help"):
		print_usage()
		sys.exit(0)

	elif opt_c in ("-v", "--version"):
		print_version()
		sys.exit(0)


# Make sure the serial port device is specified
if len(args) < 1:
	print_usage()
	sys.exit(-1)

# Open the serial port with our options
serial_fd = serial_open(args[0])
if (serial_fd < 0):
	sys.exit(-1)

console_init()
console_read_write_loop()

# Close the serial port
serial_close(serial_fd)
