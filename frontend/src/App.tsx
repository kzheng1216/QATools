import { useEffect, useState, type ReactNode } from "react";
import {
  Button,
  ConfigProvider,
  Input,
  Layout,
  Menu,
  Modal,
  Select,
  Space,
  message,
  theme,
} from "antd";
import {
  DesktopOutlined,
  ProfileOutlined,
  PlayCircleOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  RobotOutlined,
  BookOutlined,
  BgColorsOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  HistoryOutlined,
  CloudServerOutlined,
  LoginOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import DevicePage from "./pages/DevicePage";
import ProfilePage from "./pages/ProfilePage";
import RunCasePage from "./pages/RunCasePage";
import RokuTestPage from "./pages/RokuTestPage";
import TestRailCasePage from "./pages/TestRailCasePage";
import AgentPage from "./pages/AgentPage";
import ReferencePage from "./pages/ReferencePage";
import SettingsPage from "./pages/SettingsPage";
import AnalyzeHistoryPage from "./pages/AnalyzeHistoryPage";
import FileTransferPage from "./pages/FileTransferPage";
import { listTabs, adminLogin } from "./api/client";

const { Header, Sider, Content } = Layout;

type PageKey =
  | "device"
  | "profile"
  | "runcase"
  | "rokutest"
  | "testrail"
  | "agent"
  | "reference"
  | "analyzehistory"
  | "filetransfer"
  | "settings";

// Config-driven tabs. Visibility is loaded at runtime from the backend
// (/v1/config/tabs/list) so the Settings page can toggle it live. Settings
// itself is always shown so you can never lock yourself out.
const CONFIG_TABS: { key: PageKey; icon: ReactNode; label: string }[] = [
  { key: "device", icon: <DesktopOutlined />, label: "Device" },
  { key: "profile", icon: <ProfileOutlined />, label: "Profile" },
  { key: "runcase", icon: <PlayCircleOutlined />, label: "Run Case" },
  { key: "rokutest", icon: <ExperimentOutlined />, label: "Run Case in local" },
  { key: "analyzehistory", icon: <HistoryOutlined />, label: "Analyze History" },
  { key: "testrail", icon: <FileTextOutlined />, label: "TestRail Case" },
  { key: "agent", icon: <RobotOutlined />, label: "Prompt" },
  { key: "reference", icon: <BookOutlined />, label: "Reference" },
  { key: "filetransfer", icon: <CloudServerOutlined />, label: "File Transfer" },
];
const SETTINGS_TAB = { key: "settings" as PageKey, icon: <SettingOutlined />, label: "Settings" };

// ---------- Themes ----------
// Each theme picks an antd algorithm (dark or default/light) and the banner /
// sider / divider / brand colors. The selection persists in localStorage.
interface ThemeDef {
  key: string;
  label: string;
  mode: "dark" | "light";
  headerBg: string;
  siderBg: string;
  border: string;
  brand: string; // header title text color
  colorPrimary: string;
}

const THEMES: ThemeDef[] = [
  {
    key: "midnight",
    label: "Midnight (Dark)",
    mode: "dark",
    headerBg: "#0b1020",
    siderBg: "#141a2e",
    border: "#26304a",
    brand: "#c9d4ff",
    colorPrimary: "#597ef7",
  },
  {
    key: "everforest",
    label: "Everforest (Dark)",
    mode: "dark",
    headerBg: "#232a2e",
    siderBg: "#2d353b",
    border: "#4a555b",
    brand: "#d3c6aa",
    colorPrimary: "#a7c080",
  },
  {
    key: "gruvbox",
    label: "Gruvbox (Dark)",
    mode: "dark",
    headerBg: "#1d2021",
    siderBg: "#282828",
    border: "#504945",
    brand: "#ebdbb2",
    colorPrimary: "#fe8019",
  },
  {
    key: "dracula",
    label: "Dracula (Dark)",
    mode: "dark",
    headerBg: "#191a21",
    siderBg: "#282a36",
    border: "#44475a",
    brand: "#f8f8f2",
    colorPrimary: "#ff79c6",
  },
  {
    key: "catppuccin-mocha",
    label: "Catppuccin Mocha (Dark)",
    mode: "dark",
    headerBg: "#181825",
    siderBg: "#1e1e2e",
    border: "#313244",
    brand: "#cdd6f4",
    colorPrimary: "#cba6f7",
  },
  {
    key: "monokai-pro",
    label: "Monokai Pro (Dark)",
    mode: "dark",
    headerBg: "#221f22",
    siderBg: "#2d2a2e",
    border: "#403e41",
    brand: "#fcfcfa",
    colorPrimary: "#ffd866",
  },
  {
    key: "ayu-dark",
    label: "Ayu (Dark)",
    mode: "dark",
    headerBg: "#0b0e14",
    siderBg: "#0d1017",
    border: "#1d2333",
    brand: "#bfbdb6",
    colorPrimary: "#ffb454",
  },
  {
    key: "synthwave",
    label: "Synthwave (Dark)",
    mode: "dark",
    headerBg: "#1a1033",
    siderBg: "#241b3a",
    border: "#463465",
    brand: "#f7f2ff",
    colorPrimary: "#ff2e97",
  },
  {
    key: "claude-code",
    label: "Claude Code (Dark)",
    mode: "dark",
    headerBg: "#1a1917",
    siderBg: "#1f1e1d",
    border: "#3a3733",
    brand: "#f5f1eb",
    colorPrimary: "#d97757",
  },
  {
    key: "claude-night",
    label: "Claude Night (Dark)",
    mode: "dark",
    headerBg: "#14130f",
    siderBg: "#1c1a15",
    border: "#38342b",
    brand: "#ece6da",
    colorPrimary: "#cc785c",
  },
  {
    key: "github-light",
    label: "GitHub Light",
    mode: "light",
    headerBg: "#24292f",
    siderBg: "#f6f8fa",
    border: "#d0d7de",
    brand: "#ffffff",
    colorPrimary: "#0969da",
  },
  {
    key: "daylight",
    label: "Daylight (Light)",
    mode: "light",
    headerBg: "#1677ff",
    siderBg: "#ffffff",
    border: "#e5e7eb",
    brand: "#ffffff",
    colorPrimary: "#1677ff",
  },
  {
    key: "solarized-light",
    label: "Solarized (Light)",
    mode: "light",
    headerBg: "#073642",
    siderBg: "#fdf6e3",
    border: "#eee8d5",
    brand: "#fdf6e3",
    colorPrimary: "#268bd2",
  },
  {
    key: "rose-pine-dawn",
    label: "Rosé Pine (Light)",
    mode: "light",
    headerBg: "#575279",
    siderBg: "#faf4ed",
    border: "#dfdad9",
    brand: "#faf4ed",
    colorPrimary: "#b4637a",
  },
  {
    key: "catppuccin-latte",
    label: "Catppuccin Latte (Light)",
    mode: "light",
    headerBg: "#4c4f69",
    siderBg: "#eff1f5",
    border: "#ccd0da",
    brand: "#eff1f5",
    colorPrimary: "#8839ef",
  },
  {
    key: "one-light",
    label: "One Light",
    mode: "light",
    headerBg: "#383a42",
    siderBg: "#fafafa",
    border: "#e5e5e6",
    brand: "#fafafa",
    colorPrimary: "#4078f2",
  },
  {
    key: "ayu-light",
    label: "Ayu (Light)",
    mode: "light",
    headerBg: "#ff9940",
    siderBg: "#fcfcfc",
    border: "#e7e8e9",
    brand: "#ffffff",
    colorPrimary: "#f2951d",
  },
  {
    key: "nord-light",
    label: "Nord (Light)",
    mode: "light",
    headerBg: "#2e3440",
    siderBg: "#eceff4",
    border: "#d8dee9",
    brand: "#eceff4",
    colorPrimary: "#5e81ac",
  },
];

const THEME_STORAGE_KEY = "zen-theme";

function loadTheme(): ThemeDef {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  return THEMES.find((t) => t.key === saved) ?? THEMES[0];
}

// Inner shell so theme.useToken() reads the tokens from the ConfigProvider above.
function AppShell({
  currentTheme,
  onThemeChange,
}: {
  currentTheme: ThemeDef;
  onThemeChange: (key: string) => void;
}) {
  // Visibility map loaded from the backend. A tab shows unless explicitly false.
  const [visibility, setVisibility] = useState<Record<string, boolean>>({});
  // Display order: tab key -> index (from config.yml tabs key order).
  const [tabOrder, setTabOrder] = useState<Record<string, number>>({});
  const [page, setPage] = useState<PageKey>("device");
  const [collapsed, setCollapsed] = useState(false);
  // Admin gate: the Settings tab only shows after a successful Admin Login.
  const [isAdmin, setIsAdmin] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginUser, setLoginUser] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken();

  const handleAdminLogin = async () => {
    setLoggingIn(true);
    try {
      await adminLogin(loginUser.trim(), loginPass);
      setIsAdmin(true);
      setLoginOpen(false);
      setLoginUser("");
      setLoginPass("");
      message.success("Admin logged in");
    } catch (e) {
      message.error(`Login failed: ${(e as Error).message}`);
    } finally {
      setLoggingIn(false);
    }
  };

  const handleAdminLogout = () => {
    setIsAdmin(false);
    if (page === "settings") setPage("device");
    message.success("Admin logged out");
  };

  const loadVisibility = () => {
    listTabs()
      .then((tabs) => {
        const vis: Record<string, boolean> = {};
        const ord: Record<string, number> = {};
        tabs.forEach((t) => {
          vis[t.name] = t.status;
          ord[t.name] = t.order;
        });
        setVisibility(vis);
        setTabOrder(ord);
      })
      .catch(() => {
        setVisibility({});
        setTabOrder({});
      }); // on failure, show everything in the default order
  };
  useEffect(loadVisibility, []);

  // Render visible tabs in the backend-configured order (fallback: declared
  // order in CONFIG_TABS for any tab the backend didn't rank).
  const visibleTabs = CONFIG_TABS.filter((t) => visibility[t.key] !== false).sort(
    (a, b) => (tabOrder[a.key] ?? 999) - (tabOrder[b.key] ?? 999)
  );

  // If the current page got hidden, fall back to the first visible tab.
  useEffect(() => {
    if (
      page !== "settings" &&
      !visibleTabs.some((t) => t.key === page) &&
      visibleTabs.length > 0
    ) {
      setPage(visibleTabs[0].key);
    }
  }, [visibility]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    // The content column scrolls; the header stays fixed at the top and the sider
    // sticks under it, so the pinned Settings / Collapse items stay at the
    // viewport-relative bottom as the page scrolls.
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: currentTheme.headerBg,
          borderBottom: `1px solid ${currentTheme.border}`,
          position: "sticky",
          top: 0,
          zIndex: 10,
        }}
      >
        <div
          style={{
            color: currentTheme.brand,
            fontSize: 20,
            fontWeight: 600,
            letterSpacing: 0.5,
          }}
        >
          Zen
          <span style={{ fontSize: 11, fontWeight: 400, marginLeft: 6, opacity: 0.7 }}>
            Test can be very Zen
          </span>
        </div>
        <Space>
          <Select
            value={currentTheme.key}
            onChange={onThemeChange}
            size="small"
            style={{ width: 170 }}
            suffixIcon={<BgColorsOutlined style={{ color: currentTheme.brand }} />}
            options={[
              {
                label: "Dark",
                options: THEMES.filter((t) => t.mode === "dark").map((t) => ({
                  value: t.key,
                  label: t.label,
                })),
              },
              {
                label: "Light",
                options: THEMES.filter((t) => t.mode === "light").map((t) => ({
                  value: t.key,
                  label: t.label,
                })),
              },
            ]}
          />
          {isAdmin ? (
            <Button
              size="small"
              icon={<LogoutOutlined />}
              onClick={handleAdminLogout}
            >
              Admin Logout
            </Button>
          ) : (
            <Button
              size="small"
              icon={<LoginOutlined />}
              onClick={() => setLoginOpen(true)}
            >
              Admin Login
            </Button>
          )}
        </Space>
      </Header>
      <Layout>
        <Sider
          width={200}
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          collapsedWidth={64}
          trigger={null}
          style={{
            background: currentTheme.siderBg,
            borderRight: `1px solid ${currentTheme.border}`,
            // Stick to the viewport under the 64px header so the pinned Settings /
            // Collapse items stay at the viewport-relative bottom while the page
            // scrolls; the nav menu itself scrolls if it's taller than the sider.
            position: "sticky",
            top: 64,
            height: "calc(100vh - 64px)",
            overflow: "hidden",
          }}
        >
          {/* Flex column: the nav menu flexes/scrolls, Settings + Collapse are
              pinned to the bottom of the viewport-height sider. */}
          <div
            style={{
              height: "100%",
              display: "flex",
              flexDirection: "column",
              background: currentTheme.siderBg,
            }}
          >
            <Menu
              mode="inline"
              theme={currentTheme.mode}
              selectedKeys={[page]}
              onClick={({ key }) => setPage(key as PageKey)}
              style={{
                flex: "1 1 auto",
                minHeight: 0,
                overflow: "auto",
                borderRight: 0,
                background: currentTheme.siderBg,
              }}
              items={visibleTabs.map(({ key, icon, label }) => ({ key, icon, label }))}
            />
            {/* Settings is pinned at the bottom but only shown to an admin
                (after Admin Login). */}
            {isAdmin && (
              <Menu
                mode="inline"
                theme={currentTheme.mode}
                selectedKeys={[page]}
                onClick={({ key }) => setPage(key as PageKey)}
                style={{
                  flex: "0 0 auto",
                  borderRight: 0,
                  background: currentTheme.siderBg,
                }}
                items={[
                  {
                    key: SETTINGS_TAB.key,
                    icon: SETTINGS_TAB.icon,
                    label: SETTINGS_TAB.label,
                  },
                ]}
              />
            )}
            <Button
              type="text"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={() => setCollapsed((c) => !c)}
              style={{
                flex: "0 0 auto",
                height: 48,
                borderTop: `1px solid ${currentTheme.border}`,
                borderRadius: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: collapsed ? "center" : "flex-start",
                color: currentTheme.mode === "dark" ? "rgba(255,255,255,0.85)" : undefined,
              }}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            >
              {!collapsed && "Collapse"}
            </Button>
          </div>
        </Sider>
        <Content style={{ padding: 24 }}>
          <div
            style={{
              padding: 24,
              minHeight: "100%",
              background: colorBgContainer,
              borderRadius: borderRadiusLG,
            }}
          >
            {page === "device" && <DevicePage />}
            {page === "profile" && <ProfilePage />}
            {page === "runcase" && <RunCasePage />}
            {page === "rokutest" && <RokuTestPage />}
            {page === "testrail" && <TestRailCasePage />}
            {page === "agent" && <AgentPage />}
            {page === "reference" && <ReferencePage />}
            {page === "analyzehistory" && <AnalyzeHistoryPage />}
            {page === "filetransfer" && <FileTransferPage />}
            {page === "settings" && isAdmin && (
              <SettingsPage onChanged={loadVisibility} />
            )}
          </div>
        </Content>
      </Layout>

      {/* Admin login modal — gates the Settings tab. */}
      <Modal
        title="Admin Login"
        open={loginOpen}
        onOk={handleAdminLogin}
        confirmLoading={loggingIn}
        onCancel={() => setLoginOpen(false)}
        okText="Login"
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Input
            placeholder="Username"
            value={loginUser}
            autoFocus
            onChange={(e) => setLoginUser(e.target.value)}
            onPressEnter={handleAdminLogin}
          />
          <Input.Password
            placeholder="Password"
            value={loginPass}
            onChange={(e) => setLoginPass(e.target.value)}
            onPressEnter={handleAdminLogin}
          />
        </Space>
      </Modal>
    </Layout>
  );
}

// antd v5 theming via algorithm (dark/default) + a selectable palette. The
// choice persists in localStorage. CSS-in-JS, so no antd css import needed.
export default function App() {
  const [currentTheme, setCurrentTheme] = useState<ThemeDef>(loadTheme);

  const handleThemeChange = (key: string) => {
    const next = THEMES.find((t) => t.key === key);
    if (!next) return;
    setCurrentTheme(next);
    localStorage.setItem(THEME_STORAGE_KEY, key);
  };

  return (
    <ConfigProvider
      theme={{
        algorithm:
          currentTheme.mode === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: { colorPrimary: currentTheme.colorPrimary },
      }}
    >
      <AppShell currentTheme={currentTheme} onThemeChange={handleThemeChange} />
    </ConfigProvider>
  );
}
