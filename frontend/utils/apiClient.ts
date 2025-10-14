import { TokenManager } from './tokenManager';
import { router } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL } from './config';

export const apiClient = {
  async fetch(url: string, options: RequestInit = {}): Promise<Response> {
    // Check if token needs refresh before making the request
    if (await TokenManager.isAccessTokenExpired()) {
      const refreshed = await TokenManager.refreshAccessToken(API_BASE_URL);
      if (!refreshed) {
        await TokenManager.clearTokens();
        await AsyncStorage.clear();
        router.replace('/');
        throw new Error('Session expired');
      }
    }

    const token = await TokenManager.getAccessToken();
    
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    // If we get 401, try to refresh token and retry
    if (response.status === 401) {
      const refreshed = await TokenManager.refreshAccessToken(API_BASE_URL);
      if (refreshed) {
        // Retry the request with new token
        const newToken = await TokenManager.getAccessToken();
        headers['Authorization'] = `Bearer ${newToken}`;
        
        return await fetch(url, {
          ...options,
          headers,
        });
      } else {
        // Refresh failed, logout user
        await TokenManager.clearTokens();
        await AsyncStorage.clear();
        router.replace('/');
        throw new Error('Session expired');
      }
    }

    return response;
  },
};
