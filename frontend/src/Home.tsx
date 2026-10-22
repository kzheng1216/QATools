import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Table, Layout, Menu } from 'antd';
import 'antd/dist/reset.css';
import Note from './note';
import Sample_list from './sample_list';
import Other from './other';
import Chart02 from './chart/chart02';
import Chart01 from './chart/chart01';
import Chart04 from './chart/chart04';
import Chart03 from './chart/chart03';
const { Header, Content, Sider, Footer } = Layout;

const Home = () => {
    const navigate = useNavigate();
    const [activeContent, setActiveContent] = useState<'sample_list' | 'note' | 'other' | 'chart01' | 'chart02' | 'chart03' | 'chart04'>('sample_list');
    const noteName = 'My Note Page';
    const noteMsg = 'My Note Message';

    const handleLogout = () => {
        localStorage.removeItem('token');
        navigate('/login');
    };

    const handleMenuClick = (key: string) => {
        if (key === "1") {
            setActiveContent("sample_list");
        } else if (key === "2") {
            setActiveContent("note");
        } else if (key === "3") {
            setActiveContent("other");
        } else if (key === "4") {
            setActiveContent("chart01");
        } else if (key === "5") {
            setActiveContent("chart02");
        } else if (key === "6") {
            setActiveContent("chart03");
        } else if (key === "7") {
            setActiveContent("chart04");
        }
    };

    return (
        <Layout style={{ height: "100vh" }}>
            <Header
                style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                }}
            >
                <Menu
                    theme="dark"
                    mode="horizontal"
                    defaultSelectedKeys={["1"]}
                    style={{ flex: 1 }}
                >
                    <Menu.Item key="1">Home</Menu.Item>
                </Menu>
                <Button type="primary" onClick={handleLogout}>
                    Logout
                </Button>
            </Header>
            <Layout>
                <Sider width={200} theme="light">
                    <Menu
                        mode="inline"
                        defaultSelectedKeys={["1"]}
                        style={{ height: "100%", borderRight: 0 }}
                        onClick={({ key }) => handleMenuClick(key)}
                    >
                        <Menu.Item key="1">例子</Menu.Item>
                        <Menu.Item key="2">笔记列表</Menu.Item>
                        <Menu.Item key="3">其他</Menu.Item>
                        <Menu.Item key="4">[图表] - 笔记统计柱状图</Menu.Item>
                        <Menu.Item key="5">[图表] - 笔记统计趋势图</Menu.Item>
                        <Menu.Item key="6">[图表] - 03</Menu.Item>
                        <Menu.Item key="7">[图表] - 04</Menu.Item>
                    </Menu>
                </Sider>
                <Layout style={{ padding: "0 24px 24px" }}>
                    <Content style={{ padding: "20px", background: "#fff" }}>
                        {activeContent === "sample_list" && <Sample_list />}
                        {activeContent === "note" && (
                            <Note p1={noteName} p2={noteMsg} />
                        )}{" "}
                        {/* 传递 token */}
                        {activeContent === "other" && <Other />}
                        {activeContent === "chart01" && <Chart01 />}
                        {activeContent === "chart02" && <Chart02 />}
                        {activeContent === "chart03" && <Chart03 />}
                        {activeContent === "chart04" && <Chart04 />}
                    </Content>
                </Layout>
                <Sider width={200} theme="light" style={{ background: "#f0f2f5" }} />
            </Layout>
            <Footer style={{ textAlign: "center" }}>
                ©2023 Created by Your Company
            </Footer>
        </Layout>
    );
};

export default Home;
