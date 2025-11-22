# client.py - Email Client CLI dengan Select + Data Caching
import select
import socket
import sys
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

class EmailClient(object):
    """Email Client CLI dengan Select dan Data Caching"""
    
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.username = None
        self.logged_in = False
        self.sock = None
        self.connected = False
        
        # Data caching (in-memory)
        self.cache = {
            'inbox': [],
            'sent': [],
            'last_sync': None
        }
        
        # Local storage directory
        self.data_dir = "client_data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        # User-specific data file
        self.user_data_file = None
    
    def connect_to_server(self):
        """Buat persistent connection ke server"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.connected = True
            print(f"🔌 Connected to server {self.host}:{self.port}")
            return True
        except ConnectionRefusedError:
            print("❌ Cannot connect to server. Make sure server is running.")
            return False
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return False
    
    def disconnect_from_server(self):
        """Tutup koneksi ke server"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.connected = False
            print("🔌 Disconnected from server")
    
    def send_command(self, command, wait_response=True):
        """Kirim command dan terima response dengan select"""
        if not self.connected:
            if not self.connect_to_server():
                return "ERROR|Not connected to server"
        
        try:
            # Kirim command
            send(self.sock, command)
            
            if not wait_response:
                return "OK|Command sent"
            
            # Gunakan select untuk menunggu response (timeout 10 detik)
            readable, _, exceptional = select.select([self.sock], [], [self.sock], 10.0)
            
            if exceptional:
                self.connected = False
                return "ERROR|Connection error"
            
            if readable:
                response = receive(self.sock)
                return response
            else:
                return "ERROR|Server timeout"
                
        except Exception as e:
            self.connected = False
            return f"ERROR|{str(e)}"
    
    def save_user_data(self):
        """Simpan data user ke file lokal (persistent storage)"""
        if not self.username:
            return
        
        user_data = {
            'username': self.username,
            'cache': self.cache,
            'last_login': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            with open(self.user_data_file, 'w', encoding='utf-8') as f:
                json.dump(user_data, f, indent=2, ensure_ascii=False)
            print(f"💾 Data saved to {self.user_data_file}")
        except Exception as e:
            print(f"⚠️  Failed to save data: {e}")
    
    def load_user_data(self):
        """Load data user dari file lokal"""
        if not self.username:
            return
        
        self.user_data_file = os.path.join(self.data_dir, f"{self.username}_data.json")
        
        if os.path.exists(self.user_data_file):
            try:
                with open(self.user_data_file, 'r', encoding='utf-8') as f:
                    user_data = json.load(f)
                    self.cache = user_data.get('cache', self.cache)
                    print(f"📂 Loaded cached data from {self.user_data_file}")
            except Exception as e:
                print(f"⚠️  Failed to load data: {e}")
    
    def save_draft(self, draft_data):
        """Simpan draft email"""
        draft_file = os.path.join(self.data_dir, f"{self.username}_drafts.json")
        
        drafts = []
        if os.path.exists(draft_file):
            try:
                with open(draft_file, 'r', encoding='utf-8') as f:
                    drafts = json.load(f)
            except:
                drafts = []
        
        draft_data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        drafts.append(draft_data)
        
        try:
            with open(draft_file, 'w', encoding='utf-8') as f:
                json.dump(drafts, f, indent=2, ensure_ascii=False)
            print(f"💾 Draft saved!")
        except Exception as e:
            print(f"⚠️  Failed to save draft: {e}")
    
    def load_drafts(self):
        """Load draft emails"""
        draft_file = os.path.join(self.data_dir, f"{self.username}_drafts.json")
        
        if os.path.exists(draft_file):
            try:
                with open(draft_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def sync_inbox(self):
        """Sync inbox dari server dan cache"""
        response = self.send_command(f"INBOX|{self.username}")
        
        if response.startswith("EMPTY"):
            self.cache['inbox'] = []
            self.cache['last_sync'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return []
        
        if not response.startswith("OK"):
            print(f"⚠️  Sync failed: {response}")
            return self.cache['inbox']  # Return cached data
        
        # Parse response
        parts = response.split("|", 2)
        if len(parts) < 3:
            return []
        
        emails = []
        emails_data = parts[2]
        for email_str in emails_data.split(";"):
            if email_str.strip():
                email_parts = email_str.split("~")
                if len(email_parts) >= 5:
                    emails.append({
                        'id': email_parts[0],
                        'from': email_parts[1],
                        'subject': email_parts[2],
                        'timestamp': email_parts[3],
                        'read': email_parts[4] == 'READ'
                    })
        
        self.cache['inbox'] = emails
        self.cache['last_sync'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return emails
    
    def sync_sent(self):
        """Sync sent emails dari server dan cache"""
        response = self.send_command(f"SENT|{self.username}")
        
        if response.startswith("EMPTY"):
            self.cache['sent'] = []
            return []
        
        if not response.startswith("OK"):
            return self.cache['sent']
        
        # Parse response
        parts = response.split("|", 2)
        if len(parts) < 3:
            return []
        
        emails = []
        emails_data = parts[2]
        for email_str in emails_data.split(";"):
            if email_str.strip():
                email_parts = email_str.split("~")
                if len(email_parts) >= 4:
                    emails.append({
                        'id': email_parts[0],
                        'to': email_parts[1],
                        'subject': email_parts[2],
                        'timestamp': email_parts[3]
                    })
        
        self.cache['sent'] = emails
        return emails
    
    def clear_screen(self):
        """Clear terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def print_header(self, title):
        """Print header dengan border"""
        print("\n" + "=" * 70)
        print(f"  {title}")
        print("=" * 70)
    
    def print_separator(self):
        """Print separator line"""
        print("-" * 70)
    
    def register(self):
        """Register new user"""
        self.clear_screen()
        self.print_header("📝 REGISTER NEW ACCOUNT")
        
        username = input("Enter username: ").strip()
        if not username:
            print("❌ Username cannot be empty!")
            input("Press Enter to continue...")
            return
        
        password = input("Enter password: ").strip()
        if not password:
            print("❌ Password cannot be empty!")
            input("Press Enter to continue...")
            return
        
        confirm = input("Confirm password: ").strip()
        if password != confirm:
            print("❌ Passwords do not match!")
            input("Press Enter to continue...")
            return
        
        # Send to server
        command = f"REGISTER|{username}|{password}|"
        response = self.send_command(command)
        
        print()
        if response.startswith("OK"):
            print(f"✅ {response.split('|')[1]}")
        else:
            print(f"❌ {response.split('|')[1]}")
        
        input("\nPress Enter to continue...")
    
    def login(self):
        """Login user"""
        self.clear_screen()
        self.print_header("🔐 LOGIN")
        
        username = input("Enter username: ").strip()
        if not username:
            print("❌ Username cannot be empty!")
            input("Press Enter to continue...")
            return False
        
        password = input("Enter password: ").strip()
        if not password:
            print("❌ Password cannot be empty!")
            input("Press Enter to continue...")
            return False
        
        # Send to server
        command = f"LOGIN|{username}|{password}"
        response = self.send_command(command)
        
        print()
        if response.startswith("OK"):
            self.username = username
            self.logged_in = True
            
            # Load cached data
            self.load_user_data()
            
            print(f"✅ {response.split('|')[1]}")
            print(f"📂 User data directory: {self.data_dir}")
            
            # Sync data from server
            print("\n🔄 Syncing data from server...")
            self.sync_inbox()
            self.sync_sent()
            print("✅ Sync completed!")
            
            input("\nPress Enter to continue...")
            return True
        else:
            print(f"❌ {response.split('|')[1]}")
            input("\nPress Enter to continue...")
            return False
    
    def compose_email(self):
        """Compose and send email"""
        self.clear_screen()
        self.print_header(f"✉️  COMPOSE EMAIL (From: {self.username})")
        
        recipient = input("To: ").strip()
        if not recipient:
            print("❌ Recipient cannot be empty!")
            input("Press Enter to continue...")
            return
        
        subject = input("Subject: ").strip()
        subject = subject.replace("|", "-").replace("~", "-").replace(";", ",")
        if not subject:
            print("❌ Subject cannot be empty!")
            input("Press Enter to continue...")
            return
        
        print("Message (type '.' on a new line to finish, or 'SAVE' to save draft):")
        lines = []
        while True:
            line = input()
            if line == '.':
                break
            elif line.upper() == 'SAVE':
                # Save as draft
                draft = {
                    'to': recipient,
                    'subject': subject,
                    'body': '\n'.join(lines)
                }
                self.save_draft(draft)
                return
            lines.append(line)
        
        body = '\n'.join(lines)
        
        if not body:
            print("❌ Message body cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Send to server
        command = f"SEND|{self.username}|{recipient}|{subject}|{body}"
        response = self.send_command(command)
        
        print()
        if response.startswith("OK"):
            print(f"✅ {response.split('|')[1]}")
            
            # Update cache
            self.sync_sent()
            self.save_user_data()
        else:
            print(f"❌ {response.split('|')[1]}")
        
        input("\nPress Enter to continue...")
    
    def view_inbox(self):
        """View inbox with cached data"""
        self.clear_screen()
        self.print_header(f"📥 INBOX ({self.username})")
        
        # Show last sync time
        if self.cache['last_sync']:
            print(f"Last sync: {self.cache['last_sync']}")
        
        print("\nOptions: [R]efresh | [ID] Read email | [0] Back")
        choice = input("\nChoice: ").strip().upper()
        
        if choice == 'R' or not self.cache['inbox']:
            print("\n🔄 Refreshing inbox...")
            emails = self.sync_inbox()
            self.save_user_data()
        else:
            emails = self.cache['inbox']
        
        if not emails:
            print("\n📭 No emails in inbox.")
            input("\nPress Enter to continue...")
            return
        
        self.clear_screen()
        self.print_header(f"📥 INBOX ({self.username})")
        print(f"\nTotal: {len(emails)} email(s)\n")
        self.print_separator()
        
        for email in emails:
            status = "📖" if email['read'] else "📩"
            print(f"{status} [{email['id']}] From: {email['from']}")
            print(f"    Subject: {email['subject']}")
            print(f"    Date: {email['timestamp']}")
            self.print_separator()
        
        if choice and choice != '0' and choice != 'R':
            try:
                self.read_email(int(choice))
            except ValueError:
                pass
        else:
            choice = input("\nEnter email ID to read (0 to back): ").strip()
            if choice and choice != '0':
                try:
                    self.read_email(int(choice))
                except ValueError:
                    print("❌ Invalid email ID!")
                    input("Press Enter to continue...")
    
    def read_email(self, msg_id):
        """Read specific email"""
        self.clear_screen()
        self.print_header(f"📧 READ EMAIL #{msg_id}")
        
        # Get email
        command = f"READ|{self.username}|{msg_id}"
        response = self.send_command(command)
        
        if not response.startswith("OK"):
            print(f"❌ {response.split('|')[1]}")
            input("\nPress Enter to continue...")
            return
        
        # Parse email: OK|id|from|to|subject|body|timestamp
        parts = response.split("|", 6)
        if len(parts) >= 7:
            email = {
                'id': parts[1],
                'from': parts[2],
                'to': parts[3],
                'subject': parts[4],
                'body': parts[5],
                'timestamp': parts[6]
            }
            
            print(f"\nFrom: {email['from']}")
            print(f"To: {email['to']}")
            print(f"Date: {email['timestamp']}")
            print(f"Subject: {email['subject']}")
            self.print_separator()
            print(f"\n{email['body']}\n")
            self.print_separator()
            
            # Update cache (mark as read)
            for cached_email in self.cache['inbox']:
                if cached_email['id'] == str(msg_id):
                    cached_email['read'] = True
            self.save_user_data()
            
            # Options
            print("\nOptions:")
            print("  [1] Delete this email")
            print("  [2] Forward this email")
            print("  [3] Export to .txt")
            print("  [4] Reply to sender")
            print("  [0] Back")
            
            choice = input("\nChoose option: ").strip()
            
            if choice == '1':
                self.delete_email(msg_id)
            elif choice == '2':
                self.forward_email(msg_id)
            elif choice == '3':
                self.export_email(msg_id)
            elif choice == '4':
                self.reply_email(email)
    
    def reply_email(self, original_email):
        """Reply to email"""
        self.clear_screen()
        self.print_header(f"↩️  REPLY TO: {original_email['from']}")
        
        print(f"Original Subject: {original_email['subject']}")
        print(f"\nYour reply (type '.' on a new line to finish):")
        
        lines = []
        while True:
            line = input()
            if line == '.':
                break
            lines.append(line)
        
        body = '\n'.join(lines)
        
        if not body:
            print("❌ Reply cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Compose reply
        reply_subject = f"RE: {original_email['subject']}"
        reply_body = f"{body}\n\n--- Original Message ---\n{original_email['body']}"
        
        command = f"SEND|{self.username}|{original_email['from']}|{reply_subject}|{reply_body}"
        response = self.send_command(command)
        
        if response.startswith("OK"):
            print(f"\n✅ Reply sent!")
            self.sync_sent()
            self.save_user_data()
        else:
            print(f"\n❌ {response.split('|')[1]}")
        
        input("\nPress Enter to continue...")
    
    def delete_email(self, msg_id):
        """Delete email"""
        confirm = input(f"\n⚠️  Delete email #{msg_id}? (y/n): ").strip().lower()
        
        if confirm == 'y':
            command = f"DELETE|{self.username}|{msg_id}"
            response = self.send_command(command)
            
            if response.startswith("OK"):
                print(f"✅ {response.split('|')[1]}")
                
                # Update cache
                self.sync_inbox()
                self.save_user_data()
            else:
                print(f"❌ {response.split('|')[1]}")
        
        input("\nPress Enter to continue...")
    
    def forward_email(self, msg_id):
        """Forward email"""
        recipient = input("\nForward to (username): ").strip()
        
        if not recipient:
            print("❌ Recipient cannot be empty!")
            input("Press Enter to continue...")
            return
        
        command = f"FORWARD|{self.username}|{msg_id}|{recipient}"
        response = self.send_command(command)
        
        if response.startswith("OK"):
            print(f"✅ {response.split('|')[1]}")
            self.sync_sent()
            self.save_user_data()
        else:
            print(f"❌ {response.split('|')[1]}")
        
        input("\nPress Enter to continue...")
    
    def export_email(self, msg_id):
        """Export email to .txt"""
        command = f"EXPORT|{self.username}|{msg_id}"
        response = self.send_command(command)
        
        if response.startswith("OK"):
            parts = response.split("|", 2)
            
            if len(parts) == 3:
                filename = parts[1]
                content = parts[2]
                filepath = os.path.join(self.data_dir, filename)
                
                try:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"✅ Email exported successfully to: {filepath}")
                except Exception as e:
                    print(f"❌ Failed to write file: {e}")
            else:
                print("❌ Invalid response format from server")
        else:
            print(f"❌ {response.split('|')[1]}")
        
        input("\nPress Enter to continue...")
    
    def view_sent(self):
        """View sent emails"""
        self.clear_screen()
        self.print_header(f"📤 SENT EMAILS ({self.username})")
        
        print("\nOptions: [R]efresh | [0] Back")
        choice = input("\nChoice: ").strip().upper()
        
        if choice == 'R' or not self.cache['sent']:
            print("\n🔄 Refreshing sent emails...")
            emails = self.sync_sent()
            self.save_user_data()
        else:
            emails = self.cache['sent']
        
        if not emails:
            print("\n📭 No sent emails.")
            input("\nPress Enter to continue...")
            return
        
        self.clear_screen()
        self.print_header(f"📤 SENT EMAILS ({self.username})")
        print(f"\nTotal: {len(emails)} email(s)\n")
        self.print_separator()
        
        for email in emails:
            print(f"📨 [{email['id']}] To: {email['to']}")
            print(f"    Subject: {email['subject']}")
            print(f"    Date: {email['timestamp']}")
            self.print_separator()
        
        input("\nPress Enter to continue...")
    
    def view_drafts(self):
        """View saved drafts"""
        self.clear_screen()
        self.print_header(f"📝 DRAFTS ({self.username})")
        
        drafts = self.load_drafts()
        
        if not drafts:
            print("\n📭 No drafts saved.")
            input("\nPress Enter to continue...")
            return
        
        print(f"\nTotal: {len(drafts)} draft(s)\n")
        self.print_separator()
        
        for i, draft in enumerate(drafts, 1):
            print(f"📝 [{i}] To: {draft.get('to', 'N/A')}")
            print(f"    Subject: {draft.get('subject', 'N/A')}")
            print(f"    Saved: {draft.get('timestamp', 'N/A')}")
            self.print_separator()
        
        input("\nPress Enter to continue...")
    
    def view_status(self):
        """View account status"""
        self.clear_screen()
        self.print_header(f"📊 ACCOUNT STATUS ({self.username})")
        
        command = f"STATUS|{self.username}"
        response = self.send_command(command)
        
        if response.startswith("OK"):
            parts = response.split("|")
            print(f"\n{parts[1]}")
            print(f"{parts[2]}")
        else:
            print(f"❌ {response.split('|')[1]}")
        
        # Show cache info
        print(f"\n💾 Cached Data:")
        print(f"   - Inbox: {len(self.cache['inbox'])} emails")
        print(f"   - Sent: {len(self.cache['sent'])} emails")
        print(f"   - Last sync: {self.cache['last_sync']}")
        print(f"   - Data file: {self.user_data_file}")
        
        drafts = self.load_drafts()
        print(f"   - Drafts: {len(drafts)}")
        
        input("\nPress Enter to continue...")
    
    def main_menu(self):
        """Main menu after login"""
        while self.logged_in:
            self.clear_screen()
            self.print_header(f"📧 SIGMAIL - Welcome {self.username}!")
            
            print("\n1. 📥 View Inbox")
            print("2. 📤 View Sent")
            print("3. ✉️  Compose Email")
            print("4. 📝 View Drafts")
            print("5. 📊 Account Status")
            print("6. 🔄 Sync All Data")
            print("7. 🚪 Logout")
            print("8. ❌ Exit")
            
            choice = input("\nChoose option [1-8]: ").strip()
            
            if choice == '1':
                self.view_inbox()
            elif choice == '2':
                self.view_sent()
            elif choice == '3':
                self.compose_email()
            elif choice == '4':
                self.view_drafts()
            elif choice == '5':
                self.view_status()
            elif choice == '6':
                print("\n🔄 Syncing all data...")
                self.sync_inbox()
                self.sync_sent()
                self.save_user_data()
                print("✅ Sync completed!")
                input("Press Enter to continue...")
            elif choice == '7':
                # Save data before logout
                self.save_user_data()
                self.disconnect_from_server()
                self.logged_in = False
                self.username = None
                print("\n👋 Logged out successfully!")
                input("Press Enter to continue...")
            elif choice == '8':
                self.save_user_data()
                self.disconnect_from_server()
                print("\n👋 Goodbye!")
                sys.exit(0)
            else:
                print("❌ Invalid option!")
                input("Press Enter to continue...")
    
    def run(self):
        """Main client loop"""
        # Connect to server
        if not self.connect_to_server():
            print("❌ Cannot start client without server connection!")
            sys.exit(1)
        
        self.clear_screen()
        print("=" * 70)
        print("  📧 SIGMAIL CLIENT - CLI MODE with SELECT")
        print("=" * 70)
        print(f"  🌐 Server: {self.host}:{self.port}")
        print(f"  💾 Data Directory: {self.data_dir}")
        print("=" * 70)
        
        try:
            while True:
                if not self.logged_in:
                    self.clear_screen()
                    self.print_header("📧 SIGMAIL - Welcome!")
                    
                    print("\n1. 🔐 Login")
                    print("2. 📝 Register")
                    print("3. ❌ Exit")
                    
                    choice = input("\nChoose option [1-3]: ").strip()
                    
                    if choice == '1':
                        if self.login():
                            self.main_menu()
                    elif choice == '2':
                        self.register()
                    elif choice == '3':
                        print("\n👋 Goodbye!")
                        break
                    else:
                        print("❌ Invalid option!")
                        input("Press Enter to continue...")
                else:
                    self.main_menu()
        finally:
            self.disconnect_from_server()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='📧 SigMail Client - CLI Mode with Select')
    parser.add_argument('--host', default='127.0.0.1',
                        help='Server host address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=9000,
                        help='Server port (default: 9000)')
    
    args = parser.parse_args()
    
    client = EmailClient(args.host, args.port)
    
    try:
        client.run()
    except KeyboardInterrupt:
        print("\n\n👋 Client interrupted. Goodbye!")
        client.disconnect_from_server()
        sys.exit(0)