import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
import threading
import time  # <<<--- YENİ: Zaman aşımı için eklendi

# KULLANICININ SAĞLADIĞI DALI KOMUT LİSTESİ
# (Kategori bilgisi eklenmiştir)
DALI_COMMANDS = [
    # General Commands
    ("0", "OFF", "General"),
    ("1", "UP", "General"),
    ("2", "DOWN", "General"),
    ("3", "STEP UP", "General"),
    ("4", "STEP DOWN", "General"),
    ("5", "RECALL MAX LEVEL", "General"),
    ("6", "RECALL MIN LEVEL", "General"),
    ("7", "STEP DOWN AND OFF", "General"),
    ("8", "ON AND STEP UP", "General"),
    ("16", "GO TO SCENE (0-15)", "General - Scene"),  # 16-31 arası
    ("32", "RESET", "General"),
    ("33", "STORE ACTUAL LEVEL IN THE DTR", "General - DTR"),
    ("42", "STORE THE DTR AS MAX LEVEL", "General - DTR"),
    ("43", "STORE THE DTR AS MIN LEVEL", "General - DTR"),
    ("44", "STORE THE DTR AS SYSTEM FAILURE LEVEL", "General - DTR"),
    ("45", "STORE THE DTR AS POWER ON LEVEL", "General - DTR"),
    ("46", "STORE THE DTR AS FADE TIME", "General - DTR"),
    ("47", "STORE THE DTR AS FADE RATE", "General - DTR"),
    ("64", "STORE THE DTR AS SCENE (0-15)", "General - Scene"),  # 64-79 arası
    ("80", "REMOVE FROM SCENE (0-15)", "General - Scene"),  # 80-95 arası
    ("96", "ADD TO GROUP (0-15)", "General - Group"),  # 96-111 arası
    ("112", "REMOVE FROM GROUP (0-15)", "General - Group"),  # 112-127 arası
    ("128", "STORE DTR AS SHORT ADDRESS", "General - DTR"),
    ("129", "MEMORY ENABLE WRITE (Özel)", "General - DTR"),
    ("144", "QUERY STATUS", "Query"),
    ("145", "QUERY BALLAST", "Query"),
    ("146", "QUERY LAMP FAILURE", "Query"),
    ("147", "QUERY LAMP POWER ON", "Query"),
    ("148", "QUERY LIMIT ERROR", "Query"),
    ("149", "QUERY RESET STATE", "Query"),
    ("150", "QUERY MISSING SHORT ADDRESS", "Query"),
    ("151", "QUERY VERSION NUMBER", "Query"),
    ("152", "QUERY CONTENT DTR", "Query - DTR"),
    ("153", "QUERY DEVICE TYPE", "Query"),
    ("154", "QUERY PHYSICAL MINIMUM LEVEL", "Query"),
    ("155", "QUERY POWER FAILURE", "Query"),
    ("160", "QUERY ACTUAL LEVEL", "Query - Level"),
    ("161", "QUERY MAX LEVEL", "Query - Level"),
    ("162", "QUERY MIN LEVEL", "Query - Level"),
    ("163", "QUERY POWER ON LEVEL", "Query - Level"),
    ("164", "QUERY SYSTEM FAILURE LEVEL", "Query - Level"),
    ("165", "QUERY FADE TIME/FADE RATE", "Query - Level"),
    ("176", "QUERY SCENE LEVEL (0-15)", "Query - Scene"),  # 176-191 arası
    ("192", "QUERY GROUPS 0-7", "Query - Group"),
    ("193", "QUERY GROUPS 8-15", "Query - Group"),
    ("194", "QUERY RANDOM ADDRESS (H)", "Query - Addr"),
    ("195", "QUERY RANDOM ADDRESS (M)", "Query - Addr"),
    ("196", "QUERY RANDOM ADDRESS (L)", "Query - Addr"),

    # Special Commands
    ("256", "TERMINATE", "Special"),
    ("257", "DATA TRANSFER REGISTER (DTR)", "Special - DTR"),
    ("258", "INITIALISE", "Special - Commission"),
    ("259", "RANDOMISE", "Special - Commission"),
    ("260", "COMPARE", "Special - Commission"),
    ("261", "WITHDRAW", "Special - Commission"),
    ("264", "SEARCHADDRH", "Special - Addr"),
    ("265", "SEARCHADDRM", "Special - Addr"),
    ("266", "SEARCHADDRL", "Special - Addr"),
    ("267", "PROGRAM SHORT ADDRESS", "Special - Addr"),
    ("268", "VERIFY SHORT ADDRESS", "Special - Addr"),
    ("269", "QUERY SHORT ADDRESS", "Special - Addr"),
    ("270", "PHYSICAL SELECTION", "Special - Commission"),
    ("272", "ENABLE DEVICE TYPE X", "Special"),
]


class DaliApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 DALI Master GUI (Gelişmiş)")
        self.root.geometry("750x750")

        self.ser = None
        self.stop_read_thread = threading.Event()

        # --- OTOMATİK ADRESLEME (COMMISSIONING) İÇİN YENİ DEĞİŞKENLER ---
        self.commission_status_var = tk.StringVar(value="Boşta")
        self.commission_start_addr_var = tk.StringVar(value="0")
        self.found_devices_count = 0

        # Binary search state
        self.search_address = 0x000000  # Mevcut 24-bit arama adresi
        self.current_bit_index = 23  # 23'ten 0'a doğru arayacağız
        self.current_short_address = 0  # Atanacak kısa adres (0-63)
        self.is_searching = False  # Otomatik arama aktif mi?
        self.commission_state = "IDLE"  # State machine durumu

        # ESP32 ile iletişim bayrakları
        self.waiting_for_compare = False  # COMPARE yanıtı bekleniyor mu?
        self.compare_response = "NO"  # Varsayılan yanıt "HAYIR"
        self.expecting_rx_frame_content = False

        self.temp_search_address = 0
        self.search_addr_h = 0
        self.search_addr_m = 0
        self.search_addr_l = 0

        # <<<--- YENİ: Aktif bekleme (polling) için zaman aşımı
        self.response_deadline = 0
        # --- EKLENTİ SONU ---

        # Ana çerçeveleri oluştur
        self.create_connection_frame()
        self.create_addressing_frame()
        self.create_command_tabs()
        self.create_log_frame()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_connection_frame(self):
        frame = ttk.LabelFrame(self.root, text="Bağlantı Ayarları", padding=10)
        frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame, text="Port:").pack(side=tk.LEFT, padx=5)
        self.port_var = tk.StringVar(self.root)
        ports = self.find_serial_ports()
        self.port_var.set(ports[0])
        self.port_menu = ttk.OptionMenu(frame, self.port_var, *ports)
        self.port_menu.pack(side=tk.LEFT, padx=5)

        refresh_btn = ttk.Button(frame, text="Yenile", command=self.update_port_list)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        ttk.Label(frame, text="Baud Rate:").pack(side=tk.LEFT, padx=5)
        self.baud_var = tk.StringVar(self.root, value="115200")
        baud_rates = ['9600', '19200', '38400', '57600', '115200']
        baud_combo = ttk.Combobox(frame, textvariable=self.baud_var, values=baud_rates, width=10)
        baud_combo.pack(side=tk.LEFT, padx=5)

        self.connect_btn = ttk.Button(frame, text="Bağlan", command=self.connect_serial)
        self.connect_btn.pack(side=tk.LEFT, padx=10)

        self.status_label = ttk.Label(frame, text="Bağlı Değil", foreground="red", font=('Arial', 10, 'bold'))
        self.status_label.pack(side=tk.RIGHT, padx=10)

    def create_addressing_frame(self):
        frame = ttk.LabelFrame(self.root, text="Adresleme", padding=10)
        frame.pack(fill="x", padx=10, pady=5)

        self.addr_type_var = tk.StringVar(value="s")
        ttk.Label(frame, text="Adres Tipi:").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Radiobutton(frame, text="Short (s)", variable=self.addr_type_var, value="s",
                        command=self.update_address_field).grid(row=0, column=1, sticky=tk.W)
        ttk.Radiobutton(frame, text="Group (g)", variable=self.addr_type_var, value="g",
                        command=self.update_address_field).grid(row=0, column=2, sticky=tk.W)
        ttk.Radiobutton(frame, text="Broadcast (b)", variable=self.addr_type_var, value="b",
                        command=self.update_address_field).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(frame, text="Adres / Veri (0-255):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.addr_val = tk.StringVar()
        self.addr_entry = ttk.Entry(frame, textvariable=self.addr_val, width=10)
        self.addr_entry.grid(row=1, column=1, sticky=tk.W, columnspan=2, pady=5)

        self.cmd_type_var = tk.StringVar(value="c")
        ttk.Label(frame, text="Komut Tipi:").grid(row=0, column=4, sticky=tk.W, padx=20)
        ttk.Radiobutton(frame, text="Command (c)", variable=self.cmd_type_var, value="c").grid(row=0, column=5,
                                                                                               sticky=tk.W)
        ttk.Radiobutton(frame, text="Direct Arc (d)", variable=self.cmd_type_var, value="d").grid(row=0, column=6,
                                                                                                  sticky=tk.W)

    def update_address_field(self):
        addr_type = self.addr_type_var.get()
        if addr_type == 'b':
            self.addr_val.set("31")
            self.addr_entry.config(state="disabled")
        else:
            self.addr_entry.config(state="normal")
            if self.addr_val.get() == "31":
                self.addr_val.set("")

    def create_command_tabs(self):
        notebook = ttk.Notebook(self.root, padding=10)
        notebook.pack(fill="x", padx=10, pady=5)

        manual_tab = ttk.Frame(notebook)
        notebook.add(manual_tab, text="Manuel Komut")
        self.create_manual_tab(manual_tab)

        quick_tab = ttk.Frame(notebook)
        notebook.add(quick_tab, text="Hızlı Komutlar")
        self.create_quick_tab(quick_tab)

        scene_tab = ttk.Frame(notebook)
        notebook.add(scene_tab, text="Scene Arayüzü")
        self.create_scene_tab(scene_tab)

        group_tab = ttk.Frame(notebook)
        notebook.add(group_tab, text="Group Arayüzü")
        self.create_group_tab(group_tab)

        query_tab = ttk.Frame(notebook)
        notebook.add(query_tab, text="Query Arayüzü")
        self.create_query_tab(query_tab)

        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="Ayarlar")
        self.create_settings_tab(settings_tab)

        comm_tab = ttk.Frame(notebook)
        notebook.add(comm_tab, text="Devreye Alma (Adresleme)")
        self.create_commissioning_tab(comm_tab)

        ref_tab = ttk.Frame(notebook)
        notebook.add(ref_tab, text="Komut Kılavuzu")
        self.create_reference_tab(ref_tab)

    def create_manual_tab(self, tab):
        frame = ttk.Frame(tab, padding=10)
        frame.pack(pady=20)

        ttk.Label(frame, text="Komut (0-255+):").pack(side=tk.LEFT, padx=5)
        self.manual_cmd_val = tk.StringVar()
        manual_entry = ttk.Entry(frame, textvariable=self.manual_cmd_val, width=10)
        manual_entry.pack(side=tk.LEFT, padx=5)

        send_btn = ttk.Button(frame, text="Gönder", command=self.send_manual_command)
        send_btn.pack(side=tk.LEFT, padx=10)

    def create_quick_tab(self, tab):
        control_frame = ttk.LabelFrame(tab, text="Kontrol Kumandası", padding=10)
        control_frame.pack(pady=10, padx=10)
        btn_width = 12
        (ttk.Button(control_frame, text="STEP UP (3)", width=btn_width,
                    command=lambda: self.send_quick_command(3))
         .grid(row=0, column=1, columnspan=2, padx=5, pady=5))
        (ttk.Button(control_frame, text="MIN (6)", width=btn_width,
                    command=lambda: self.send_quick_command(6))
         .grid(row=1, column=0, padx=5, pady=5))
        (ttk.Button(control_frame, text="OFF (0)", width=btn_width,
                    command=lambda: self.send_quick_command(0))
         .grid(row=1, column=1, padx=5, pady=5))
        (ttk.Button(control_frame, text="ON (8)", width=btn_width,
                    command=lambda: self.send_quick_command(8))
         .grid(row=1, column=2, padx=5, pady=5))
        (ttk.Button(control_frame, text="MAX (5)", width=btn_width,
                    command=lambda: self.send_quick_command(5))
         .grid(row=1, column=3, padx=5, pady=5))
        (ttk.Button(control_frame, text="STEP DOWN (4)", width=btn_width,
                    command=lambda: self.send_quick_command(4))
         .grid(row=2, column=1, columnspan=2, padx=5, pady=5))

    def create_scene_tab(self, tab):
        go_frame = ttk.LabelFrame(tab, text="Sahneye Git (Go To Scene)", padding=10)
        go_frame.pack(pady=5, fill="x", padx=10)
        ttk.Label(go_frame, text="Sahne (0-15):").pack(side=tk.LEFT, padx=5)
        self.scene_goto_var = tk.StringVar(value="0")
        (ttk.Spinbox(go_frame, from_=0, to=15, textvariable=self.scene_goto_var, width=5)
         .pack(side=tk.LEFT, padx=5))
        (ttk.Button(go_frame, text="Git (Komut 16+)", command=self.send_go_to_scene)
         .pack(side=tk.LEFT, padx=10))

        set_frame = ttk.LabelFrame(tab, text="Mevcut Seviyeyi Sahne Olarak Kaydet (Set Scene)", padding=10)
        set_frame.pack(pady=5, fill="x", padx=10)
        ttk.Label(set_frame, text="Sahne (0-15):").pack(side=tk.LEFT, padx=5)
        self.scene_set_var = tk.StringVar(value="0")
        (ttk.Spinbox(set_frame, from_=0, to=15, textvariable=self.scene_set_var, width=5)
         .pack(side=tk.LEFT, padx=5))
        (ttk.Button(set_frame, text="Kaydet (Komut 33 -> 64+)", command=self.send_set_scene)
         .pack(side=tk.LEFT, padx=10))

        remove_frame = ttk.LabelFrame(tab, text="Sahneden Kaldır (Remove From Scene)", padding=10)
        remove_frame.pack(pady=5, fill="x", padx=10)
        ttk.Label(remove_frame, text="Sahne (0-15):").pack(side=tk.LEFT, padx=5)
        self.scene_remove_var = tk.StringVar(value="0")
        (ttk.Spinbox(remove_frame, from_=0, to=15, textvariable=self.scene_remove_var, width=5)
         .pack(side=tk.LEFT, padx=5))
        (ttk.Button(remove_frame, text="Kaldır (Komut 80+)", command=self.send_remove_from_scene)
         .pack(side=tk.LEFT, padx=10))

    def create_group_tab(self, tab):
        add_frame = ttk.LabelFrame(tab, text="Gruba Ekle (Add to Group)", padding=10)
        add_frame.pack(pady=10, fill="x", padx=10)
        ttk.Label(add_frame, text="Grup (0-15):").pack(side=tk.LEFT, padx=5)
        self.group_add_var = tk.StringVar(value="0")
        (ttk.Spinbox(add_frame, from_=0, to=15, textvariable=self.group_add_var, width=5)
         .pack(side=tk.LEFT, padx=5))
        (ttk.Button(add_frame, text="Ekle (Komut 96+)", command=self.send_add_to_group)
         .pack(side=tk.LEFT, padx=10))

        remove_frame = ttk.LabelFrame(tab, text="Gruptan Kaldır (Remove from Group)", padding=10)
        remove_frame.pack(pady=10, fill="x", padx=10)
        ttk.Label(remove_frame, text="Grup (0-15):").pack(side=tk.LEFT, padx=5)
        self.group_remove_var = tk.StringVar(value="0")
        (ttk.Spinbox(remove_frame, from_=0, to=15, textvariable=self.group_remove_var, width=5)
         .pack(side=tk.LEFT, padx=5))
        (ttk.Button(remove_frame, text="Kaldır (Komut 112+)", command=self.send_remove_from_group)
         .pack(side=tk.LEFT, padx=10))

    def create_query_tab(self, tab):
        left_frame = ttk.Frame(tab, padding=5)
        left_frame.pack(side=tk.LEFT, fill='y', padx=5, pady=5)
        right_frame = ttk.Frame(tab, padding=5)
        right_frame.pack(side=tk.LEFT, fill='both', expand=True, padx=5, pady=5)

        query_frame_genel = ttk.LabelFrame(left_frame, text="Genel Durum Sorguları", padding=10)
        query_frame_genel.pack(fill="x", pady=5)
        btn_width = 30
        (ttk.Button(query_frame_genel, text="QUERY STATUS (144)", width=btn_width,
                    command=lambda: self.send_quick_command(144))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_genel, text="QUERY ACTUAL LEVEL (160)", width=btn_width,
                    command=lambda: self.send_quick_command(160))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_genel, text="QUERY LAMP FAIL (146)", width=btn_width,
                    command=lambda: self.send_quick_command(146))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_genel, text="QUERY LAMP POWER ON (147)", width=btn_width,
                    command=lambda: self.send_quick_command(147))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_genel, text="QUERY LIMIT ERROR (148)", width=btn_width,
                    command=lambda: self.send_quick_command(148))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_genel, text="QUERY MISSING SHORT ADDR (150)", width=btn_width,
                    command=lambda: self.send_quick_command(150))
         .pack(padx=5, pady=3, fill="x"))

        query_frame_param = ttk.LabelFrame(right_frame, text="Parametre/Grup Sorguları", padding=10)
        query_frame_param.pack(fill="x", pady=5)
        (ttk.Button(query_frame_param, text="QUERY MAX LEVEL (161)", width=btn_width,
                    command=lambda: self.send_quick_command(161))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_param, text="QUERY MIN LEVEL (162)", width=btn_width,
                    command=lambda: self.send_quick_command(162))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_param, text="QUERY CONTENT DTR (152)", width=btn_width,
                    command=lambda: self.send_quick_command(152))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_param, text="QUERY GROUPS 0-7 (192)", width=btn_width,
                    command=lambda: self.send_quick_command(192))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(query_frame_param, text="QUERY GROUPS 8-15 (193)", width=btn_width,
                    command=lambda: self.send_quick_command(193))
         .pack(padx=5, pady=3, fill="x"))

        query_frame_scene = ttk.LabelFrame(right_frame, text="Sahne Seviyesi Sorgula", padding=10)
        query_frame_scene.pack(fill="x", pady=5)
        ttk.Label(query_frame_scene, text="Sahne (0-15):").pack(side=tk.LEFT, padx=5)
        self.query_scene_var = tk.StringVar(value="0")
        (ttk.Spinbox(query_frame_scene, from_=0, to=15, textvariable=self.query_scene_var, width=5)
         .pack(side=tk.LEFT, padx=5))
        (ttk.Button(query_frame_scene, text="Sorgula (Komut 176+)", command=self.send_query_scene_level)
         .pack(side=tk.LEFT, padx=10))

    def create_settings_tab(self, tab):
        btn_width = 35
        dtr_frame = ttk.LabelFrame(tab, text="Parametre Kaydetme (DTR'den)", padding=10)
        dtr_frame.pack(pady=5, padx=10, fill="x")
        (ttk.Button(dtr_frame, text="STORE DTR AS MAX LEVEL (42)", width=btn_width,
                    command=lambda: self.send_quick_command(42))
         .grid(row=0, column=0, padx=5, pady=3, sticky="ew"))
        (ttk.Button(dtr_frame, text="STORE DTR AS MIN LEVEL (43)", width=btn_width,
                    command=lambda: self.send_quick_command(43))
         .grid(row=1, column=0, padx=5, pady=3, sticky="ew"))
        (ttk.Button(dtr_frame, text="STORE DTR AS POWER ON LVL (45)", width=btn_width,
                    command=lambda: self.send_quick_command(45))
         .grid(row=0, column=1, padx=5, pady=3, sticky="ew"))
        (ttk.Button(dtr_frame, text="STORE DTR AS SYS FAIL LVL (44)", width=btn_width,
                    command=lambda: self.send_quick_command(44))
         .grid(row=1, column=1, padx=5, pady=3, sticky="ew"))
        (ttk.Button(dtr_frame, text="STORE DTR AS FADE TIME (46)", width=btn_width,
                    command=lambda: self.send_quick_command(46))
         .grid(row=0, column=2, padx=5, pady=3, sticky="ew"))
        (ttk.Button(dtr_frame, text="STORE DTR AS FADE RATE (47)", width=btn_width,
                    command=lambda: self.send_quick_command(47))
         .grid(row=1, column=2, padx=5, pady=3, sticky="ew"))
        dtr_frame.columnconfigure((0, 1, 2), weight=1)

        special_frame = ttk.LabelFrame(tab, text="Özel Kayıt Komutları", padding=10)
        special_frame.pack(pady=5, padx=10, fill="x")
        (ttk.Button(special_frame, text="STORE DTR AS SHORT ADDRESS (128)", width=btn_width,
                    command=lambda: self.send_quick_command(128))
         .pack(padx=5, pady=3, fill="x"))
        (ttk.Button(special_frame, text="Bellek Yazmayı Etkinleştir (129)", width=btn_width,
                    command=lambda: self.send_quick_command(129))
         .pack(padx=5, pady=3, fill="x"))

    def create_commissioning_tab(self, tab):
        btn_width = 30
        core_frame = ttk.LabelFrame(tab, text="Adresleme Prosedürü (Manuel)", padding=10)
        core_frame.pack(pady=5, padx=10, fill="x")
        (ttk.Button(core_frame, text="INITIALISE (258)", width=btn_width,
                    command=lambda: self.send_quick_command(258))
         .grid(row=0, column=0, padx=5, pady=3, sticky="ew"))
        (ttk.Button(core_frame, text="RANDOMISE (259)", width=btn_width,
                    command=lambda: self.send_quick_command(259))
         .grid(row=1, column=0, padx=5, pady=3, sticky="ew"))
        (ttk.Button(core_frame, text="COMPARE (260)", width=btn_width,
                    command=lambda: self.send_quick_command(260))
         .grid(row=0, column=1, padx=5, pady=3, sticky="ew"))
        (ttk.Button(core_frame, text="WITHDRAW (261)", width=btn_width,
                    command=lambda: self.send_quick_command(261))
         .grid(row=1, column=1, padx=5, pady=3, sticky="ew"))
        (ttk.Button(core_frame, text="TERMINATE (256)", width=btn_width,
                    command=lambda: self.send_quick_command(256))
         .grid(row=0, column=2, padx=5, pady=3, sticky="ew"))
        core_frame.columnconfigure((0, 1, 2), weight=1)

        data_frame = ttk.LabelFrame(tab, text="Adres/Veri Ayarlama (Manuel)", padding=10)
        data_frame.pack(pady=5, padx=10, fill="x")
        note_label = ttk.Label(data_frame,
                               text="Not: Bu komutlar, 'Adresleme' bölümündeki 'Adres / Veri' alanını veri olarak kullanır.",
                               font=('Arial', 8, 'italic'),
                               foreground="gray")
        note_label.grid(row=0, column=0, columnspan=3, padx=5, pady=5, sticky="w")
        (ttk.Button(data_frame, text="DATA TRANSFER REGISTER (DTR) (257)", width=btn_width,
                    command=lambda: self.send_quick_command(257))
         .grid(row=1, column=0, columnspan=3, padx=5, pady=3, sticky="ew"))
        (ttk.Button(data_frame, text="SEARCHADDRH (264)", width=btn_width,
                    command=lambda: self.send_quick_command(264))
         .grid(row=2, column=0, padx=5, pady=3, sticky="ew"))
        (ttk.Button(data_frame, text="SEARCHADDRM (265)", width=btn_width,
                    command=lambda: self.send_quick_command(265))
         .grid(row=2, column=1, padx=5, pady=3, sticky="ew"))
        (ttk.Button(data_frame, text="SEARCHADDRL (266)", width=btn_width,
                    command=lambda: self.send_quick_command(266))
         .grid(row=2, column=2, padx=5, pady=3, sticky="ew"))
        (ttk.Button(data_frame, text="PROGRAM SHORT ADDRESS (267)", width=btn_width,
                    command=lambda: self.send_quick_command(267))
         .grid(row=3, column=0, padx=5, pady=3, sticky="ew"))
        (ttk.Button(data_frame, text="VERIFY SHORT ADDRESS (268)", width=btn_width,
                    command=lambda: self.send_quick_command(268))
         .grid(row=3, column=1, padx=5, pady=3, sticky="ew"))
        (ttk.Button(data_frame, text="QUERY SHORT ADDRESS (269)", width=btn_width,
                    command=lambda: self.send_quick_command(269))
         .grid(row=3, column=2, padx=5, pady=3, sticky="ew"))
        data_frame.columnconfigure((0, 1, 2), weight=1)

        auto_frame = ttk.LabelFrame(tab, text="Otomatik Adresleme (Binary Search)", padding=10)
        auto_frame.pack(pady=10, padx=10, fill="x")

        control_sub_frame = ttk.Frame(auto_frame)
        control_sub_frame.pack(fill="x")
        ttk.Label(control_sub_frame, text="Atanacak Başlangıç Adresi:").pack(side=tk.LEFT, padx=5, pady=5)
        start_addr_spinbox = ttk.Spinbox(control_sub_frame, from_=0, to=63,
                                         textvariable=self.commission_start_addr_var, width=5)
        start_addr_spinbox.pack(side=tk.LEFT, padx=5, pady=5)
        self.start_comm_btn = ttk.Button(control_sub_frame, text="Taramayı Başlat", command=self.start_commissioning)
        self.start_comm_btn.pack(side=tk.LEFT, padx=10, pady=5)
        self.stop_comm_btn = ttk.Button(control_sub_frame, text="Durdur", command=self.stop_commissioning,
                                        state="disabled")
        self.stop_comm_btn.pack(side=tk.LEFT, padx=5, pady=5)

        status_sub_frame = ttk.Frame(auto_frame)
        status_sub_frame.pack(fill="x", pady=5)
        ttk.Label(status_sub_frame, text="Durum:").pack(side=tk.LEFT, padx=5)
        self.commission_status_label = ttk.Label(status_sub_frame, textvariable=self.commission_status_var,
                                                 font=('Arial', 10, 'bold'))
        self.commission_status_label.pack(side=tk.LEFT, padx=5)

        log_label = ttk.Label(auto_frame, text="Adresleme Logu:")
        log_label.pack(fill="x", padx=5, pady=(5, 0))
        self.commission_log = scrolledtext.ScrolledText(auto_frame, height=6, state="disabled",
                                                        font=('Courier New', 9))
        self.commission_log.pack(fill="x", expand=True, padx=5, pady=(0, 5))

    def create_reference_tab(self, tab):
        frame = ttk.Frame(tab, padding=10)
        frame.pack(fill="both", expand=True)

        cols = ("Komut (Dec)", "Açıklama", "Kategori")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        self.tree.column("Açıklama", width=300)
        for cmd in DALI_COMMANDS:
            self.tree.insert("", "end", values=cmd)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill="y")

        send_btn = ttk.Button(tab, text="Seçili Komutu Gönder", command=self.send_selected_command)
        send_btn.pack(pady=10)

    def create_log_frame(self):
        log_frame = ttk.LabelFrame(self.root, text="ESP32 Çıktısı", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, state="disabled", font=('Courier New', 9))
        self.log_text.pack(fill="both", expand=True)

        self.log_text.tag_config('send_tag', foreground="blue", font=('Courier New', 9, 'bold'))
        self.log_text.tag_config('esp32_tag', foreground="black")
        self.log_text.tag_config('info_tag', foreground="gray", font=('Courier New', 9, 'italic'))

    # --- Fonksiyonlar ---

    def find_serial_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        return ports if ports else ["Port Bulunamadı"]

    def update_port_list(self):
        ports = self.find_serial_ports()
        menu = self.port_menu['menu']
        menu.delete(0, 'end')
        for port in ports:
            menu.add_command(label=port, command=lambda p=port: self.port_var.set(p))
        self.port_var.set(ports[0])

    def log_message(self, message, tag=None):
        self.log_text.config(state=tk.NORMAL)
        if tag:
            self.log_text.insert(tk.END, message + "\n", tag)
        else:
            self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state=tk.DISABLED)
        self.log_text.see(tk.END)

    # --- *** BU FONKSİYON GÜNCELLENDİ (YENİ COMPARE LOGİĞİ) *** ---
    def read_from_serial(self):
        while not self.stop_read_thread.is_set() and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    line = self.ser.readline().decode('ascii', errors='ignore').strip()
                    if line:

                        # --- GÜNCELLENMİŞ OTOMATİK ADRESLEME LOGİĞİ ---
                        # Bu log mesajı, ESP32'nin `COMPARE` komutuna yanıt aldığını gösterir
                        # Yeni logunuzda bu satırın "[Main Task]..." kısmını kaldırdınız
                        if "RX (16-bit): [" in line:
                            if self.waiting_for_compare:
                                # Yanıtın içeriğini kontrol et
                                try:
                                    # line = "ESP32: RX (16-bit): [ 11111111 | 11000000 ]"
                                    bits_part = line.split('[')[1].strip()
                                    y_byte_bits = bits_part.split('|')[0].strip()  # "1111 1111"

                                    # ESP32'nin 0xFF (EVET) yanıtı
                                    if y_byte_bits == "1111 1111":
                                        self.compare_response = "YES"
                                except Exception as e:
                                    print(f"RX frame parse hatası: {e}")
                                    # (Yanıt "NO" olarak kalacak)

                            # Her iki durumda da (yanıt 11111111 olsun veya olmasın),
                            # bir yanıt aldığımızı ve artık beklemeyi durdurabileceğimizi
                            # state machine'e bildirmek için bu bayrağı "NO"ya çekebiliriz
                            # ANCAK, "AWAITING" state'i bunu zaten zaman aşımı ile hallediyor
                            # Sadece "YES" durumunu yakalamamız yeterli.

                        # --- GÜNCELLEME SONU ---

                        self.root.after(0, self.log_message, f"ESP32: {line}", "esp32_tag")
            except serial.SerialException:
                self.root.after(0, self.disconnect_serial)
                break
            except Exception as e:
                print(f"Okuma hatası: {e}")
                break

    # --- *** GÜNCELLEME SONU *** ---

    def connect_serial(self):
        port = self.port_var.get()
        baud = self.baud_var.get()
        if port == "Port Bulunamadı":
            messagebox.showerror("Hata", "Geçerli bir port seçin.")
            return
        try:
            self.ser = serial.Serial(port, int(baud), timeout=0.1)
            self.status_label.config(text=f"Bağlandı: {port} @ {baud}", foreground="green")
            self.connect_btn.config(text="Bağlantıyı Kes", command=self.disconnect_serial)
            self.port_menu.config(state="disabled")
            self.stop_read_thread.clear()
            reader_thread = threading.Thread(target=self.read_from_serial, daemon=True)
            reader_thread.start()
            self.log_message(f"Bağlantı kuruldu: {port}", "info_tag")
        except serial.SerialException as e:
            messagebox.showerror("Bağlantı Hatası", f"Porta bağlanılamadı:\n{e}")

    def disconnect_serial(self):
        self.stop_read_thread.set()
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception as e:
                print(f"Kapatma hatası: {e}")
        self.ser = None
        self.status_label.config(text="Bağlı Değil", foreground="red")
        self.connect_btn.config(text="Bağlan", command=self.connect_serial)
        self.port_menu.config(state="normal")
        self.update_port_list()
        self.log_message("Bağlantı kesildi.", "info_tag")

    # --- YARDIMCI FONKSİYONLAR ---

    def check_command_type_is_c(self):
        if self.cmd_type_var.get() != 'c':
            messagebox.showwarning("Geçersiz Mod",
                                   "Bu komutu kullanmak için 'Adresleme' bölümünde "
                                   "'Command (c)' seçili olmalıdır.\n\n"
                                   "('Direct Arc (d)' seçiliyken 'OFF' (0) göndermek, "
                                   "cihazı kapatmak yerine %0 seviyesine götürür.)")
            return False
        return True

    def send_quick_command(self, cmd_val):
        if not self.check_command_type_is_c():
            return
        self.send_dali_command(cmd_val)

    def send_go_to_scene(self):
        if not self.check_command_type_is_c():
            return
        try:
            scene_num = int(self.scene_goto_var.get())
            if not (0 <= scene_num <= 15): raise ValueError
            self.send_dali_command(16 + scene_num)
        except ValueError:
            messagebox.showerror("Geçersiz Girdi", "Sahne numarası 0-15 arası bir sayı olmalıdır.")

    def send_set_scene(self):
        if not self.check_command_type_is_c():
            return
        try:
            scene_num = int(self.scene_set_var.get())
            if not (0 <= scene_num <= 15): raise ValueError
            self.send_dali_command(33)
            command = 64 + scene_num
            self.send_dali_command(command)
            self.log_message(f"Bilgi: Sahne {scene_num} ayarlandı (Komut 33 -> {command})", "info_tag")
        except ValueError:
            messagebox.showerror("Geçersiz Girdi", "Sahne numarası 0-15 arası bir sayı olmalıdır.")

    def send_remove_from_scene(self):
        if not self.check_command_type_is_c():
            return
        try:
            scene_num = int(self.scene_remove_var.get())
            if not (0 <= scene_num <= 15): raise ValueError
            command = 80 + scene_num
            self.send_dali_command(command)
            self.log_message(f"Bilgi: Sahne {scene_num}'dan kaldırıldı (Komut {command})", "info_tag")
        except ValueError:
            messagebox.showerror("Geçersiz Girdi", "Sahne numarası 0-15 arası bir sayı olmalıdır.")

    def send_add_to_group(self):
        if not self.check_command_type_is_c():
            return
        try:
            group_num = int(self.group_add_var.get())
            if not (0 <= group_num <= 15): raise ValueError
            command = 96 + group_num
            self.send_dali_command(command)
            self.log_message(f"Bilgi: Grup {group_num}'a eklendi (Komut {command})", "info_tag")
        except ValueError:
            messagebox.showerror("Geçersiz Girdi", "Grup numarası 0-15 arası bir sayı olmalıdır.")

    def send_remove_from_group(self):
        if not self.check_command_type_is_c():
            return
        try:
            group_num = int(self.group_remove_var.get())
            if not (0 <= group_num <= 15): raise ValueError
            command = 112 + group_num
            self.send_dali_command(command)
            self.log_message(f"Bilgi: Grup {group_num}'dan kaldırıldı (Komut {command})", "info_tag")
        except ValueError:
            messagebox.showerror("Geçersiz Girdi", "Grup numarası 0-15 arası bir sayı olmalıdır.")

    def send_query_scene_level(self):
        if not self.check_command_type_is_c():
            return
        try:
            scene_num = int(self.query_scene_var.get())
            if not (0 <= scene_num <= 15): raise ValueError
            command = 176 + scene_num
            self.send_dali_command(command)
            self.log_message(f"Bilgi: Sahne {scene_num} seviyesi sorgulandı (Komut {command})", "info_tag")
        except ValueError:
            messagebox.showerror("Geçersiz Girdi", "Sahne numarası 0-15 arası bir sayı olmalıdır.")

    # --- ANA GÖNDERME FONKSİYONLARI ---

    def send_dali_command(self, command_value):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Hata", "Cihaz bağlı değil. Lütfen önce 'Bağlan' butonuna basın.")
            return

        addr_type_choice = self.addr_type_var.get()
        cmd_type = self.cmd_type_var.get()
        addr_val_str = self.addr_val.get()
        cmd_val_str = str(command_value)

        if not addr_val_str and addr_type_choice != 'b':
            messagebox.showerror("Geçersiz Girdi", "Lütfen 'Adresleme' bölümüne bir Adres / Veri girin.")
            return

        try:
            addr = int(addr_val_str)
            cmd = int(cmd_val_str)
            if not (0 <= addr <= 255):
                messagebox.showerror("Geçersiz Girdi", f"Adres/Veri {addr} geçerli değil (0-255 olmalı).")
                return
            if not (0 <= cmd <= 511):
                messagebox.showerror("Geçersiz Girdi", f"Komut {cmd} geçerli aralıkta değil (0-511).")
                return
        except ValueError:
            messagebox.showerror("Geçersiz Girdi", "Adres/Veri ve Komut geçerli sayılar olmalıdır.")
            return

        if addr_type_choice == 'b':
            type_char = 'g'
        else:
            type_char = addr_type_choice

        command_string = f"{type_char}{cmd_type} {addr} {cmd}\n"

        try:
            self.ser.write(command_string.encode('ascii'))
            self.log_message(f"GÖNDERİLDİ: {command_string.strip()}", "send_tag")
        except serial.SerialException as e:
            messagebox.showerror("Gönderme Hatası", f"Veri gönderilemedi:\n{e}")
            self.disconnect_serial()

    def send_manual_command(self):
        cmd = self.manual_cmd_val.get()
        if cmd:
            self.send_dali_command(cmd)
        else:
            messagebox.showwarning("Girdi Yok", "Lütfen bir komut değeri girin.")

    def send_selected_command(self):
        selected_item = self.tree.focus()
        if not selected_item:
            messagebox.showwarning("Seçim Yok", "Lütfen kılavuzdan bir komut seçin.")
            return
        item_values = self.tree.item(selected_item, 'values')
        cmd = item_values[0]
        self.send_dali_command(cmd)

    # --- OTOMATİK ADRESLEME (COMMISSIONING) FONKSİYONLARI ---

    def log_commission(self, message):
        """Otomatik adresleme loguna yazar."""
        self.commission_log.config(state=tk.NORMAL)
        self.commission_log.insert(tk.END, message + "\n")
        self.commission_log.see(tk.END)
        self.commission_log.config(state=tk.DISABLED)

    def update_commission_status(self, status):
        """Durum etiketini günceller."""
        self.commission_status_var.set(status)

    def start_commissioning(self):
        """Otomatik adresleme sürecini başlatır."""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Hata", "Cihaz bağlı değil. Lütfen önce 'Bağlan' butonuna basın.")
            return

        self.commission_log.config(state=tk.NORMAL)
        self.commission_log.delete('1.0', tk.END)
        self.commission_log.config(state=tk.DISABLED)

        self.found_devices_count = 0
        try:
            self.current_short_address = int(self.commission_start_addr_var.get())
            if not (0 <= self.current_short_address <= 63): raise ValueError
        except ValueError:
            messagebox.showerror("Hata", "Başlangıç adresi 0-63 arası bir sayı olmalı.")
            return

        self.start_comm_btn.config(state="disabled")
        self.stop_comm_btn.config(state="normal")
        self.is_searching = True
        self.commission_state = "START"
        self.root.after(10, self.run_commission_step)

    def stop_commissioning(self):
        """Otomatik adresleme sürecini durdurur."""
        self.is_searching = False
        self.commission_state = "IDLE"
        self.start_comm_btn.config(state="normal")
        self.stop_comm_btn.config(state="disabled")
        self.update_commission_status("Durduruldu.")

    def send_special_command(self, cmd_val, data=0):
        """
        Adresleme komutlarını 'sc' (Special Command) formatında gönderir.
        """
        if not self.ser or not self.ser.is_open:
            self.stop_commissioning()
            messagebox.showwarning("Hata", "Bağlantı kesildi.")
            return

        command_string = f"sc {data} {cmd_val}\n"
        try:
            self.ser.write(command_string.encode('ascii'))
            self.log_message(f"GÖNDERİLDİ: {command_string.strip()}", "send_tag")
        except serial.SerialException as e:
            self.stop_commissioning()
            messagebox.showerror("Gönderme Hatası", f"Veri gönderilemedi:\n{e}")

    # --- *** BU FONKSİYON GÜNCELLENDİ (AKTİF BEKLEME / POLLING) *** ---
    def run_commission_step(self):
        """
        Adresleme state machine'i. GUI'yi dondurmamak için aktif bekleme (polling) yapar.
        """
        if not self.is_searching:
            return  # Durdurma komutu geldiyse çık

        # Her komut arası ESP32'nin 'loop' döngüsünün
        # tamamlanıp yeni komutu almaya hazır olması için güvenli bir bekleme süresi
        COMMAND_DELAY = 500  # 500ms (ESP32'nin komutu işleyip DALI hattına göndermesi için)

        # DALI yanıtı bekleme süresi (COMPARE sonrası)
        # Yanıt gelmezse "HAYIR" varsaymak için
        RESPONSE_POLL_TIMEOUT = 3.0  # 3 Saniye (Aktif bekleme zaman aşımı)

        # -----------------------------------------------------------------
        # STATE 1: Başlangıç
        # -----------------------------------------------------------------
        if self.commission_state == "START":
            self.update_commission_status("Başlatılıyor (INITIALIZE)...")
            self.log_commission("Adresleme prosedürü başlatıldı.")
            self.send_special_command(258)  # INITIALIZE
            self.commission_state = "START_2"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "START_2":
            self.send_special_command(258)  # INITIALIZE (Tekrar)
            self.commission_state = "RANDOMIZE"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        # -----------------------------------------------------------------
        # STATE 2: Randomize
        # -----------------------------------------------------------------
        elif self.commission_state == "RANDOMIZE":
            self.update_commission_status("Cihazlara rastgele adres atanıyor (RANDOMIZE)...")
            self.log_commission("RANDOMIZE gönderildi.")
            self.send_special_command(259)  # RANDOMIZE
            self.commission_state = "SEARCH_BIT_START"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        # -----------------------------------------------------------------
        # STATE 3: Binary Search (Bit Arama) Döngüsü
        # -----------------------------------------------------------------
        elif self.commission_state == "SEARCH_BIT_START":
            if self.current_bit_index < 0:
                # 24 bitin tamamı arandı, doğrulama adımına geç
                self.commission_state = "CHECK_FOUND_START"
                self.root.after(10, self.run_commission_step)
                return

            self.temp_search_address = self.search_address | (1 << self.current_bit_index)
            self.update_commission_status(
                f"Aranıyor... (Bit {self.current_bit_index}) Adres: 0x{self.temp_search_address:06X}")

            self.commission_state = "SEND_SEARCH_H"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "SEND_SEARCH_H":
            h = (self.temp_search_address >> 16) & 0xFF
            self.send_special_command(264, h)
            self.commission_state = "SEND_SEARCH_M"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "SEND_SEARCH_M":
            m = (self.temp_search_address >> 8) & 0xFF
            self.send_special_command(265, m)
            self.commission_state = "SEND_SEARCH_L"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "SEND_SEARCH_L":
            l = self.temp_search_address & 0xFF
            self.send_special_command(266, l)
            self.commission_state = "SEND_COMPARE"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "SEND_COMPARE":
            self.waiting_for_compare = True
            self.expecting_rx_frame_content = False
            self.compare_response = "NO"  # Varsayılan yanıt
            self.send_special_command(260)  # COMPARE gönder

            # Zaman aşımı için son tarihi ayarla (3 saniye sonrası)
            self.response_deadline = time.time() + RESPONSE_POLL_TIMEOUT
            self.commission_state = "AWAITING_RESPONSE"
            self.root.after(100, self.run_commission_step)  # 100ms sonra yanıtı kontrol etmeye başla

        elif self.commission_state == "AWAITING_RESPONSE":
            # Yanıt geldi mi?
            if self.compare_response == "YES":
                self.waiting_for_compare = False
                self.commission_state = "PROCESS_COMPARE_RESPONSE"
                self.root.after(10, self.run_commission_step)  # Hemen işlemeye geç
                return

            # Zaman aşımı oldu mu?
            if time.time() > self.response_deadline:
                self.waiting_for_compare = False
                # Yanıt gelmedi, 'compare_response' zaten "NO"
                self.commission_state = "PROCESS_COMPARE_RESPONSE"
                self.root.after(10, self.run_commission_step)  # İşlemeye geç
                return

            # Henüz yanıt yok ve zaman aşımı olmadı, 100ms daha bekle
            self.root.after(100, self.run_commission_step)

        elif self.commission_state == "PROCESS_COMPARE_RESPONSE":
            response = self.compare_response

            if response == "YES":
                self.log_commission(f"  Bit {self.current_bit_index}: EVET (Cihaz var)")
            else:
                self.search_address |= (1 << self.current_bit_index)
                self.log_commission(f"  Bit {self.current_bit_index}: HAYIR (Cihaz yok)")

            self.current_bit_index -= 1  # Bir sonraki bite geç
            self.commission_state = "SEARCH_BIT_START"  # Döngünün başına dön
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        # -----------------------------------------------------------------
        # STATE 4: Cihazı Doğrula (Arama bitti, bulunan son adresi doğrula)
        # -----------------------------------------------------------------
        elif self.commission_state == "CHECK_FOUND_START":
            self.update_commission_status(f"Adres doğrulanıyor: 0x{self.search_address:06X}")
            self.search_addr_h = (self.search_address >> 16) & 0xFF
            self.search_addr_m = (self.search_address >> 8) & 0xFF
            self.search_addr_l = self.search_address & 0xFF

            self.send_special_command(264, self.search_addr_h)
            self.commission_state = "CHECK_FOUND_M"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "CHECK_FOUND_M":
            self.send_special_command(265, self.search_addr_m)
            self.commission_state = "CHECK_FOUND_L"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "CHECK_FOUND_L":
            self.send_special_command(266, self.search_addr_l)
            self.commission_state = "CHECK_FOUND_COMPARE"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "CHECK_FOUND_COMPARE":
            self.waiting_for_compare = True
            self.expecting_rx_frame_content = False
            self.compare_response = "NO"
            self.send_special_command(260)  # Son kez COMPARE

            # Zaman aşımı için son tarihi ayarla
            self.response_deadline = time.time() + RESPONSE_POLL_TIMEOUT
            self.commission_state = "AWAITING_FINAL_RESPONSE"
            self.root.after(100, self.run_commission_step)  # Kontrol etmeye başla

        elif self.commission_state == "AWAITING_FINAL_RESPONSE":
            # Yanıt geldi mi?
            if self.compare_response == "YES":
                self.waiting_for_compare = False
                self.commission_state = "PROGRAM_DEVICE"
                self.root.after(10, self.run_commission_step)
                return

            # Zaman aşımı oldu mu?
            if time.time() > self.response_deadline:
                self.waiting_for_compare = False
                # Yanıt gelmedi, 'compare_response' zaten "NO"
                self.commission_state = "PROGRAM_DEVICE"
                self.root.after(10, self.run_commission_step)
                return

            # Henüz yanıt yok ve zaman aşımı olmadı, 100ms daha bekle
            self.root.after(100, self.run_commission_step)

        # -----------------------------------------------------------------
        # STATE 5: Cihazı Programla ve Döngü
        # -----------------------------------------------------------------
        elif self.commission_state == "PROGRAM_DEVICE":
            self.waiting_for_compare = False
            self.expecting_rx_frame_content = False

            if self.compare_response == "NO":
                self.log_commission("\nTarama tamamlandı. Başka cihaz bulunamadı.")
                self.update_commission_status("Tamamlandı.")
                self.stop_commissioning()  # Bitir
                return

            self.log_commission(f"Cihaz bulundu! Random Addr: 0x{self.search_address:06X}")
            new_short_addr = self.current_short_address

            program_data = (new_short_addr << 1) | 1
            self.update_commission_status(f"Adres {new_short_addr} programlanıyor...")
            self.log_commission(f"PROGRAM_SHORT_ADDRESS (Adres {new_short_addr}) gönderiliyor.")

            self.send_special_command(267, program_data)

            self.commission_state = "SEND_WITHDRAW"
            self.root.after(COMMAND_DELAY, self.run_commission_step)

        elif self.commission_state == "SEND_WITHDRAW":
            self.log_commission("WITHDRAW gönderildi.")
            self.send_special_command(261)  # SEARCHADDR hala ayarlı

            self.found_devices_count += 1
            self.current_short_address += 1

            self.commission_state = "SEARCH_BIT_START"  # Döngüyü yeniden başlat
            self.root.after(COMMAND_DELAY, self.run_commission_step)

    # --- FONKSİYON GRUBU SONU ---

    def on_closing(self):
        self.stop_commissioning()
        self.disconnect_serial()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = DaliApp(root)
    root.mainloop()