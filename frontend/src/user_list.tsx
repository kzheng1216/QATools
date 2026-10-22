import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { Button, Card, List } from 'antd';

const Userlist: React.FC = () => {
    const { param01, param02 } = useLocation().state || {};

    let token = localStorage.getItem('token');
    const [user_data, setData] = useState([]);
    const config = {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    };

    const fetchData = async () => {
        try {
            const response = await axios.get('http://localhost:9882/api/users', config);
            const data = response.data;
            setData(data);

            for (let i = 0; i < data.length; i++) {
                console.log('--' + data[i].id + ' | ' + data[i].name + ' | ' + data[i].email)
            }

        } catch (error) {
            console.error('Error fetching data:', error);
        }
    };

    const renderUsers = () => {
        return (
            <List
                dataSource={user_data}
                renderItem={({ email, id, name }) => (
                    <Card style={{ width: 600, marginBottom: 16 }}>
                        <p>ID: {id}</p>
                        <p>Name: {name}</p>
                        <p>Email: {email}</p>
                    </Card>
                )}
            />
        );
    };

    return (
        <div>
            <p>-- Param data from home page: {param01} | {param02} --</p>
            <Button type="primary" onClick={fetchData}>Fetch Users</Button>
            <div style={{ marginTop: 20 }}>
                <h2>User List</h2>
                {user_data.length > 0 ? (
                    <div>{renderUsers()}</div>
                ) : (
                    <p>Loading...</p>
                )}
            </div>
        </div>
    );
};

export default Userlist;
