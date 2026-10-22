import React, { useEffect, useState } from 'react';
import { Spin, Alert } from 'antd';
import axios from 'axios';

const RunTestcasesReportHtml: React.FC = () => {
    let token = localStorage.getItem('token');
    const [htmlData, setHtmlData] = useState('');
    const config = {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    };

    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await axios.post('http://localhost:9882/api/run_tests', {
                    "mark_type": "ui",
                    "report_type": "html"
                }, config);
                setHtmlData(response.data);
            } catch (error) {
                console.error('Error fetching data:', error);
                setError((error as any)?.message || 'An error occurred');
            } finally {
                setIsLoading(false);
            }
        };

        fetchData();
    }, []);

    if (isLoading) {
        return (
            <div style={{ textAlign: 'center', marginTop: '20px' }}>
                <Spin size="large" />
            </div>
        );
    }

    if (error) {
        return (
            <div style={{ margin: '20px' }}>
                <Alert message="Error" description={error} type="error" showIcon />
            </div>
        );
    }

    return (
        <div style={{ padding: '20px' }}>
            <div dangerouslySetInnerHTML={{ __html: htmlData }} />
        </div>
    );
};

export default RunTestcasesReportHtml;