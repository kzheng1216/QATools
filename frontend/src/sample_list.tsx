import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table } from 'antd';


const Sample_list = () => {
    const navigate = useNavigate();
    const dataSource = [
        { id: 100, name: 'show user list', category: '', description: 'show user list', linkText: 'user_list', onClick: () => navigate('/user_list', { state: { param01: '123', param02: 456 } }) },
        { id: 200, name: 'run testcases html', category: '', description: 'run testcases html', linkText: 'run testcases html', onClick: () => navigate('/run_testcases_report_html') },
        { id: 201, name: 'run testcases json', category: '', description: 'run testcases json', linkText: 'run testcases json', onClick: () => navigate('/run_testcases_report_json') },
        { id: 300, name: '显示图片', category: '', description: '显示图片', linkText: 'case01', onClick: () => navigate('/cases/case01') },
        { id: 300, name: '列表显示', category: '', description: '列表显示', linkText: 'case02', onClick: () => navigate('/cases/case02') },
        { id: 300, name: '', category: '', description: '', linkText: 'case03', onClick: () => navigate('/cases/case03') },
        { id: 300, name: 'Count 增加/减少', category: '', description: 'Count 增加/减少', linkText: 'case04', onClick: () => navigate('/cases/case04') },
        { id: 300, name: '最新的count/上次的count', category: '', description: '最新的count/上次的count', linkText: 'caseHook', onClick: () => navigate('/cases/caseHook') },
        { id: 350, name: 'case 5', category: '', description: 'Param: 组件测试传参数1, 组件测试传参数2', linkText: 'case05', onClick: () => navigate('/cases/case05') },
        { id: 350, name: 'useState例子', category: '', description: '', linkText: 'UseState01', onClick: () => navigate('/cases/UseState01') },
        { id: 350, name: '组件之间的参数传递', category: '', description: '组件之间的参数传递', linkText: 'case07', onClick: () => navigate('/cases/case07') },
        { id: 350, name: 'useEffect例子', category: '', description: 'useEffect例子', linkText: 'UseEffect01', onClick: () => navigate('/cases/UseEffect01') },
        { id: 350, name: '', category: '', description: '', linkText: 'case09', onClick: () => navigate('/cases/case09') },
        { id: 350, name: 'Case list', category: '', description: 'Case list', linkText: 'case_redux01', onClick: () => navigate('/cases/redux/Counter') },
        { id: 380, name: 'Redux Counter', category: '', description: '', linkText: 'case_table01', onClick: () => navigate('/cases/table/case_table01') },
        { id: 900, name: 'Web Socket Sample', category: '', description: '', linkText: 'wcase01', onClick: () => navigate('/cases/websocket/wcase01') }
    ];
    const [filteredData] = useState(dataSource);
    const columns = [
        { title: 'ID', dataIndex: 'id', key: 'id' },
        { title: 'Name', dataIndex: 'name', key: 'name' },
        { title: 'Category', dataIndex: 'category', key: 'category' },
        { title: 'Description', dataIndex: 'description', key: 'description' },
        {
            title: 'Link',
            dataIndex: 'link',
            key: 'link',
            render: (_: any, record: { onClick: () => void; linkText: string }) => (
                <a onClick={record.onClick}>{record.linkText}</a>
            ),
        },
    ];

    return (
        <div>
            <Table dataSource={filteredData} columns={columns} rowKey="id" pagination={false} />
        </div>
    );
};

export default Sample_list;
