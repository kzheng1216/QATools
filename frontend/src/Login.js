import React, {useState} from 'react';
import {useNavigate, useLocation} from 'react-router-dom';
import axios from 'axios';
import {Form, Input, Button, Alert} from 'antd';

const Login = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const navigate = useNavigate();
    const location = useLocation();
    const {from} = location.state || {from: {pathname: "/home"}};
    const login_api_url = 'http://localhost:9882/auth/login';

    const [error, setError] = useState('');

    const handleSubmit = async () => {
        try {
            const response = await axios.post(login_api_url, {
                username,
                password,
            });
            console.log('Login successful:', response.data);

            localStorage.setItem('token', response.data.token);
            navigate(from, {replace: true});
        } catch (error) {
            console.error('Login failed:', error);
            setError(error.toString());
        }
    };

    return (
        <section style={{padding: '2rem'}}>
            <Form
                onFinish={handleSubmit}
                style={{maxWidth: 400, margin: '0 auto'}}
                layout="vertical"
            >
                <Form.Item label="Username" name="username" rules={[{required: true, message: 'Please input your username!'}]}>
                    <Input
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                    />
                </Form.Item>
                <Form.Item label="Password" name="password" rules={[{required: true, message: 'Please input your password!'}]}>
                    <Input.Password
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                    />
                </Form.Item>
                <Form.Item>
                    <Button type="primary" htmlType="submit" block>
                        Login
                    </Button>
                </Form.Item>
            </Form>

            {error && (
                <Alert
                    message="Error"
                    description={error}
                    type="error"
                    showIcon
                    style={{maxWidth: 400, margin: '1rem auto'}}
                />
            )}
        </section>
    );
};

export default Login;