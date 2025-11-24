import select
import socket
import sys
import signal
import pickle
import struct
import argparse
import os
import json
from datetime import datetime

# Utilities untuk komunikasi
def send(channel, *args):
    """Kirim data dengan pickle serialization"""
    buffer = pickle.dumps(args)
    value = socket.htonl(len(buffer))
    size = struct.pack("L", value)
    channel.send(size)
    channel.send(buffer)

def receive(channel):
    """Terima data dengan pickle deserialization"""
    size = struct.calcsize("L")
    size = channel.recv(size)
    try:
        size = socket.ntohl(struct.unpack("L", size)[0])
    except struct.error as e:
        return ''
    buf = ""
    while len(buf) < size:
        buf = channel.recv(size - len(buf))
    return pickle.loads(buf)[0]

class EmailServer(object):
    """Email Server menggunakan select untuk multiplexing I/O"""
    
    def __init__(self, host, port, backlog=5):
        self.clients = 0
        self.clientmap = {}
        self.outputs = []
        
        # Database in-memory
        self.users = {}  # {username: password}
        self.emails = []  # List of email dictionaries
        self.email_id_counter = 0
        
        # Load existing data
        self.load_server_data()
        
        # Setup socket server
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((host, port))
        
        print("=" * 70)
        print("EMAIL SERVER - CLI MODE")
        print("=" * 70)
        print(f"Server Address: {host}:{port}")
        print(f"Status: RUNNING")
        print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print("\n[SERVER] Listening for connections...")
        print("[SERVER] Press Ctrl+C to shutdown\n")
        
        self.server.listen(backlog)
        
        # Catch keyboard interrupts
        signal.signal(signal.SIGINT, self.sighandler)
    
    def save_server_data(self):
        """Simpan state server ke JSON (Panggil ini setiap ada perubahan data)"""
        data = {
            'users': self.users,
            'emails': self.emails,
            'email_id_counter': self.email_id_counter
        }
        try:
            with open('server_db.json', 'w') as f:
                json.dump(data, f, indent=2)
            print("[SERVER] Data saved successfully.")
        except Exception as e:
            print(f"[SERVER] Failed to save data: {e}")
    
    def load_server_data(self):
        """Load state server saat startup"""
        if os.path.exists('server_db.json'):
            try:
                with open('server_db.json', 'r') as f:
                    data = json.load(f)
                    self.users = data.get('users', {})
                    self.emails = data.get('emails', [])
                    self.email_id_counter = data.get('email_id_counter', 0)
            except Exception as e:
                print(f"[SERVER] Database corrupted or empty, starting fresh. Error: {e}")
        else:
            print("[SERVER] No database found. Starting fresh.")
    
    def sighandler(self, signum, frame):
        """Clean up saat shutdown"""
        print('\n\n[SERVER] Shutting down gracefully...')
        print(f"[SERVER] Total registered users: {len(self.users)}")
        print(f"[SERVER] Total emails stored: {len(self.emails)}")
        for output in self.outputs:
            output.close()
        self.server.close()
        sys.exit(0)
    
    def handle_register(self, data):
        """Handle REGISTER command: REGISTER|username|password"""
        try:
            parts = data.split("|", 2) 
            if len(parts) == 3:
                _, username, password = parts
                
                if username in self.users:
                    return "ERROR|Username already exists"
                
                self.users[username] = password
                self.save_server_data()
                print(f"[REGISTER] New user: {username}")
                return f"OK|User {username} registered successfully"
            else:
                return "ERROR|Invalid REGISTER format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_login(self, data):
        """Handle LOGIN command: LOGIN|username|password"""
        try:
            parts = data.split("|")
            if len(parts) == 3:
                _, username, password = parts
                
                if username not in self.users:
                    return "ERROR|Username not found"
                
                if self.users[username] != password:
                    return "ERROR|Invalid password"
                
                print(f"[LOGIN] User logged in: {username}")
                return f"OK|Welcome {username}!"
            else:
                return "ERROR|Invalid LOGIN format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_send(self, data):
        """Handle SEND command: SEND|from|to|subject|body"""
        try:
            parts = data.split("|", 4)  # Split max 5 parts
            if len(parts) == 5:
                _, sender, recipient, subject, body = parts
                
                # Validasi recipient exists
                if recipient not in self.users:
                    return "ERROR|Recipient not found"
                
                # Create new email
                self.email_id_counter += 1
                email = {
                    'id': self.email_id_counter,
                    'from': sender,
                    'to': recipient,
                    'subject': subject,
                    'body': body,
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'read': False
                }
                self.emails.append(email)
                self.save_server_data()
                print(f"[SEND] Email #{email['id']}: {sender} → {recipient} | '{subject}'")
                return f"OK|Email sent to {recipient}"
            else:
                return "ERROR|Invalid SEND format (need: SEND|from|to|subject|body)"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_inbox(self, data):
        """Handle INBOX command: INBOX|username"""
        try:
            parts = data.split("|")
            if len(parts) == 2:
                _, username = parts
                
                # Filter emails for this user
                inbox = [e for e in self.emails if e['to'] == username]
                
                if not inbox:
                    return "EMPTY|No emails in inbox"
                
                # Format response: OK|count|email1_data;email2_data;...
                response = f"OK|{len(inbox)}|"
                for email in inbox:
                    status = "READ" if email['read'] else "UNREAD"
                    response += f"{email['id']}~{email['from']}~{email['subject']}~{email['timestamp']}~{status};"
                
                print(f"[INBOX] User {username} has {len(inbox)} email(s)")
                return response.rstrip(';')
            else:
                return "ERROR|Invalid INBOX format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_sent(self, data):
        """Handle SENT command: SENT|username"""
        try:
            parts = data.split("|")
            if len(parts) == 2:
                _, username = parts
                
                # Filter emails sent by this user
                sent = [e for e in self.emails if e['from'] == username]
                
                if not sent:
                    return "EMPTY|No sent emails"
                
                # Format response
                response = f"OK|{len(sent)}|"
                for email in sent:
                    response += f"{email['id']}~{email['to']}~{email['subject']}~{email['timestamp']};"
                
                print(f"[SENT] User {username} has sent {len(sent)} email(s)")
                return response.rstrip(';')
            else:
                return "ERROR|Invalid SENT format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_read(self, data):
        """Handle READ command: READ|username|msg_id"""
        try:
            parts = data.split("|")
            if len(parts) == 3:
                _, username, msg_id = parts
                msg_id = int(msg_id)
                
                # Find email
                email = next((e for e in self.emails if e['id'] == msg_id), None)
                
                if not email:
                    return "ERROR|Email not found"
                
                # Check access rights
                if email['to'] != username and email['from'] != username:
                    return "ERROR|Access denied"
                
                # Mark as read if recipient
                if email['to'] == username:
                    email['read'] = True
                    self.save_server_data()
                
                # Format response: OK|id|from|to|subject|body|timestamp
                response = f"OK|{email['id']}|{email['from']}|{email['to']}|{email['subject']}|{email['body']}|{email['timestamp']}"
                
                print(f"[READ] User {username} read email #{msg_id}")
                return response
            else:
                return "ERROR|Invalid READ format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_delete(self, data):
        """Handle DELETE command: DELETE|username|msg_id"""
        try:
            parts = data.split("|")
            if len(parts) == 3:
                _, username, msg_id = parts
                msg_id = int(msg_id)
                
                # Find email
                email = next((e for e in self.emails if e['id'] == msg_id), None)
                
                if not email:
                    return "ERROR|Email not found"
                
                # Check access rights
                if email['to'] != username and email['from'] != username:
                    return "ERROR|Access denied"
                
                # Delete email
                self.emails.remove(email)
                self.save_server_data()
                print(f"[DELETE] User {username} deleted email #{msg_id}")
                return f"OK|Email #{msg_id} deleted"
            else:
                return "ERROR|Invalid DELETE format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_forward(self, data):
        """Handle FORWARD command: FORWARD|username|msg_id|new_recipient"""
        try:
            parts = data.split("|")
            if len(parts) == 4:
                _, username, msg_id, new_recipient = parts
                msg_id = int(msg_id)
                
                # Find original email
                original = next((e for e in self.emails if e['id'] == msg_id), None)
                
                if not original:
                    return "ERROR|Email not found"
                
                # Check access rights
                if original['to'] != username and original['from'] != username:
                    return "ERROR|Access denied"
                
                # Validate new recipient
                if new_recipient not in self.users:
                    return "ERROR|Recipient not found"
                
                # Create forwarded email
                self.email_id_counter += 1
                forwarded = {
                    'id': self.email_id_counter,
                    'from': username,
                    'to': new_recipient,
                    'subject': f"FWD: {original['subject']}",
                    'body': f"[Forwarded from {original['from']}]\n\n{original['body']}",
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'read': False
                }
                self.emails.append(forwarded)
                
                print(f"[FORWARD] User {username} forwarded email #{msg_id} to {new_recipient}")
                return f"OK|Email forwarded to {new_recipient}"
            else:
                return "ERROR|Invalid FORWARD format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_export(self, data):
        """Handle EXPORT command: EXPORT|username|msg_id"""
        try:
            parts = data.split("|")
            if len(parts) == 3:
                _, username, msg_id = parts
                msg_id = int(msg_id)
                
                # Find email
                email = next((e for e in self.emails if e['id'] == msg_id), None)
                
                if not email:
                    return "ERROR|Email not found"
                
                # Check access rights
                if email['to'] != username and email['from'] != username:
                    return "ERROR|Access denied"
                
                # Export to .txt file
                filename = f"email_{msg_id}_{username}.txt"
                content = (
                    f"From: {email['from']}\n"
                    f"To: {email['to']}\n"
                    f"Subject: {email['subject']}\n"
                    f"Date: {email['timestamp']}\n"
                    f"\n{email['body']}\n"
                )
                
                print(f"[EXPORT] Sending email content #{msg_id} to client")
                return f"OK|Email exported to {filename}|{content}"
            else:
                return "ERROR|Invalid EXPORT format"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def handle_status(self, data):
        """Handle STATUS command"""
        try:
            parts = data.split("|")
            if len(parts) == 2:
                _, username = parts
                
                total_inbox = len([e for e in self.emails if e['to'] == username])
                unread = len([e for e in self.emails if e['to'] == username and not e['read']])
                total_sent = len([e for e in self.emails if e['from'] == username])
                
                response = f"OK|Inbox: {total_inbox} ({unread} unread)|Sent: {total_sent}"
                return response
            else:
                total_users = len(self.users)
                total_emails = len(self.emails)
                return f"OK|Users: {total_users}|Emails: {total_emails}|Active Clients: {self.clients}"
        except Exception as e:
            return f"ERROR|{str(e)}"
    
    def process_command(self, data):
        """Process command dari client"""
        if not data:
            return "ERROR|Empty command"
        
        command = data.split("|")[0]
        
        handlers = {
            "REGISTER": self.handle_register,
            "LOGIN": self.handle_login,
            "SEND": self.handle_send,
            "INBOX": self.handle_inbox,
            "SENT": self.handle_sent,
            "READ": self.handle_read,
            "DELETE": self.handle_delete,
            "FORWARD": self.handle_forward,
            "EXPORT": self.handle_export,
            "STATUS": self.handle_status
        }
        
        handler = handlers.get(command)
        if handler:
            return handler(data)
        else:
            return f"ERROR|Unknown command '{command}'"
    
    def run(self):
        """Main server loop dengan select"""
        inputs = [self.server]
        self.outputs = []
        running = True
        
        while running:
            try:
                # Select untuk monitoring multiple sockets
                readable, writeable, exceptional = select.select(inputs, self.outputs, [], 1.0)
            except select.error as e:
                print(f"[SERVER] Select error: {e}")
                break
            
            for sock in readable:
                if sock == self.server:
                    # Handle koneksi baru
                    client, address = self.server.accept()
                    print(f"[SERVER] New connection from {address[0]}:{address[1]}")
                    
                    self.clients += 1
                    inputs.append(client)
                    self.clientmap[client] = address
                    
                else:
                    # Handle data dari client
                    try:
                        data = receive(sock)
                        
                        if data:
                            # Log command (hide password)
                            cmd_log = data.split("|")[0]
                            if "LOGIN" in data or "REGISTER" in data:
                                print(f"[SERVER] Command: {cmd_log} (credentials hidden)")
                            else:
                                print(f"[SERVER] Command: {data[:80]}...")
                            
                            # Process command
                            response = self.process_command(data)
                            
                            # Send response
                            send(sock, response)
                            print(f"[SERVER] Response: {response[:80]}...")
                            
                        else:
                            # Client disconnect
                            print(f"[SERVER] Client {self.clientmap[sock]} disconnected")
                            self.clients -= 1
                            sock.close()
                            inputs.remove(sock)
                            if sock in self.outputs:
                                self.outputs.remove(sock)
                            del self.clientmap[sock]
                            
                    except socket.error as e:
                        print(f"[SERVER] Socket error: {e}")
                        if sock in inputs:
                            inputs.remove(sock)
                        if sock in self.outputs:
                            self.outputs.remove(sock)
                        if sock in self.clientmap:
                            del self.clientmap[sock]
        
        self.server.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='SigMail Server - CLI Mode with Select')
    parser.add_argument('--host', default='0.0.0.0',
                        help='Server host address (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=9000,
                        help='Server port (default: 9000)')
    
    args = parser.parse_args()
    
    server = EmailServer(args.host, args.port)
    server.run()