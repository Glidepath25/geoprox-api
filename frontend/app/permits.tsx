import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  TouchableOpacity,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  Alert,
  Linking,
  TextInput,
  Platform,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { TokenManager } from '../utils/tokenManager';
import { API_BASE_URL } from '../utils/config';

interface Permit {
  permit_ref: string;
  created_at: string;
  updated_at: string;
  owner_username: string;
  owner_display_name: string;
  desktop: {
    status: string;
    outcome: string | null;
    summary?: any;
  };
  site: {
    status: string;
    outcome: string | null;
    summary?: {
      bituminous?: string;
      sub_base?: string;
    };
  };
  sample: {
    status: string;
    outcome: string | null;
    summary?: any;
  };
  location: {
    display: string;
    lat: number;
    lon: number;
  };
}

export default function PermitsScreen() {
  const [permits, setPermits] = useState<Permit[]>([]);
  const [filteredPermits, setFilteredPermits] = useState<Permit[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [user, setUser] = useState(null);
  const router = useRouter();

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const token = await TokenManager.getAccessToken();
      const userData = await AsyncStorage.getItem('user');
      
      if (!token) {
        router.replace('/');
        return;
      }
      
      if (userData) {
        setUser(JSON.parse(userData));
      }
      
      await loadPermits();
    } catch (error) {
      console.error('Auth check error:', error);
      router.replace('/');
    }
  };

  const loadPermits = async (search: string = '') => {
    try {
      // Check if token needs refresh
      if (await TokenManager.isAccessTokenExpired()) {
        const refreshed = await TokenManager.refreshAccessToken(API_BASE_URL);
        if (!refreshed) {
          await TokenManager.clearTokens();
          await AsyncStorage.clear();
          router.replace('/');
          return;
        }
      }

      const token = await TokenManager.getAccessToken();
      
      // Use GeoProx production endpoint
      const url = new URL(`${API_BASE_URL}/api/geoprox/permits`);
      if (search.trim()) {
        url.searchParams.append('search', search.trim());
      }
      
      const response = await fetch(url.toString(), {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setPermits(data);
        setFilteredPermits(data);
      } else if (response.status === 401) {
        // Try to refresh token
        const refreshed = await TokenManager.refreshAccessToken(API_BASE_URL);
        if (refreshed) {
          // Retry the request
          await loadPermits(search);
        } else {
          await TokenManager.clearTokens();
          await AsyncStorage.clear();
          router.replace('/');
        }
      } else {
        Alert.alert('Error', 'Failed to load permits');
      }
    } catch (error) {
      console.error('Load permits error:', error);
      Alert.alert('Error', 'Network error loading permits');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleSearch = (text: string) => {
    setSearchQuery(text);
    if (text.trim() === '') {
      setFilteredPermits(permits);
    } else {
      const filtered = permits.filter(permit =>
        permit.permit_ref.toLowerCase().includes(text.toLowerCase())
      );
      setFilteredPermits(filtered);
    }
  };

  const handleRefresh = () => {
    setRefreshing(true);
    loadPermits();
  };

  const handleLogout = async () => {
    console.log('Logout button pressed');
    
    // For web, skip confirmation dialog
    if (Platform.OS === 'web') {
      try {
        const token = await TokenManager.getAccessToken();
        
        // Call logout endpoint
        await fetch(`${API_BASE_URL}/api/mobile/auth/logout`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        });
      } catch (error) {
        console.log('Logout API error (non-critical):', error);
      } finally {
        // Clear tokens and navigate to login
        await TokenManager.clearTokens();
        await AsyncStorage.clear();
        router.replace('/');
      }
      return;
    }
    
    // For native, show confirmation
    Alert.alert(
      'Logout',
      'Are you sure you want to logout?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Logout',
          style: 'destructive',
          onPress: async () => {
            try {
              const token = await TokenManager.getAccessToken();
              
              // Call logout endpoint
              await fetch(`${API_BASE_URL}/api/mobile/auth/logout`, {
                method: 'POST',
                headers: {
                  'Authorization': `Bearer ${token}`,
                  'Content-Type': 'application/json',
                },
              });
            } catch (error) {
              console.log('Logout API error (non-critical):', error);
            } finally {
              // Clear tokens and navigate to login
              await TokenManager.clearTokens();
              await AsyncStorage.clear();
              router.replace('/');
            }
          },
        },
      ]
    );
  };

  const handlePermitPress = (permit: Permit) => {
    router.push({
      pathname: '/permit-details',
      params: { permitId: permit.permit_ref }
    });
  };

  const openGoogleMaps = (latitude: number, longitude: number) => {
    const url = `https://www.google.com/maps?q=${latitude},${longitude}`;
    Linking.openURL(url).catch(() => {
      Alert.alert('Error', 'Unable to open Google Maps');
    });
  };

  const getRiskAssessmentColor = (risk: string) => {
    switch (risk.toLowerCase()) {
      case 'low':
        return '#10b981';
      case 'medium':
        return '#f59e0b';
      case 'high':
        return '#ef4444';
      default:
        return '#6b7280';
    }
  };

  const renderPermitCard = ({ item }: { item: Permit }) => (
    <TouchableOpacity
      style={styles.permitCard}
      onPress={() => handlePermitPress(item)}
      activeOpacity={0.7}
    >
      <View style={styles.cardHeader}>
        <View style={styles.headerLeft}>
          <Text style={styles.permitNumber}>{item.permit_ref}</Text>
          <Text style={styles.permitName}>Owner: {item.owner_display_name}</Text>
        </View>
        <View style={styles.headerRight}>
          <View style={[styles.statusBadge, { backgroundColor: getStatusColor(item.desktop?.status?.toLowerCase() || 'pending') }]}>
            <Text style={styles.statusText}>{item.desktop?.status}</Text>
          </View>
        </View>
      </View>
      
      <View style={styles.cardContent}>
        <View style={styles.detailRow}>
          <Ionicons name="shield" size={16} color="#6b7280" />
          <Text style={styles.detailText}>Desktop Outcome: </Text>
          <View style={[styles.riskBadge, { backgroundColor: getRiskAssessmentColor(item.desktop?.outcome?.toLowerCase() || 'unknown') }]}>
            <Text style={styles.riskText}>{item.desktop?.outcome || 'N/A'}</Text>
          </View>
        </View>

        <View style={styles.detailRow}>
          <Ionicons name="clipboard" size={16} color="#6b7280" />
          <Text style={styles.detailText}>Site Status: </Text>
          <Text style={[styles.statusWip, { 
            color: item.site?.status === 'Completed' ? '#10b981' : 
                   item.site?.status === 'In progress' ? '#f59e0b' : '#6b7280' 
          }]}>
            {item.site?.status}
          </Text>
        </View>

        {item.site?.summary?.bituminous && item.site?.summary?.sub_base && (
          <View style={styles.detailRow}>
            <View style={styles.resultsContainer}>
              <Text style={styles.resultLabel}>Bituminous: </Text>
              <View style={[styles.resultBadge, { backgroundColor: item.site?.summary?.bituminous?.toLowerCase() === 'green' ? '#10b981' : '#ef4444' }]}>
                <Text style={styles.resultText}>{item.site?.summary?.bituminous}</Text>
              </View>
              <Text style={styles.resultLabel}> - Sub-Base: </Text>
              <View style={[styles.resultBadge, { backgroundColor: item.site?.summary?.sub_base?.toLowerCase() === 'green' ? '#10b981' : '#ef4444' }]}>
                <Text style={styles.resultText}>{item.site?.summary?.sub_base}</Text>
              </View>
            </View>
          </View>
        )}

        <View style={styles.detailRow}>
          <Ionicons name="beaker" size={16} color="#6b7280" />
          <Text style={styles.detailText}>Sample Status: </Text>
          <Text style={[styles.statusWip, { 
            color: item.sample?.status === 'Completed' ? '#10b981' : 
                   item.sample?.status === 'In progress' ? '#f59e0b' : '#6b7280' 
          }]}>
            {item.sample?.status}
          </Text>
        </View>

        <View style={styles.detailRow}>
          <Ionicons name="chevron-forward" size={20} color="#9ca3af" />
          <Text style={styles.detailText}>Tap for details</Text>
        </View>
      </View>
      
      <View style={styles.cardFooter}>
        <Text style={styles.addressText}>{item.location.display}</Text>
        <View style={styles.footerRight}>
          {item.desktop?.status === 'completed' ? (
            <View style={styles.completedBadge}>
              <Ionicons name="checkmark-circle" size={16} color="#10b981" />
              <Text style={styles.completedText}>Inspected</Text>
            </View>
          ) : (
            <View style={styles.pendingBadge}>
              <Ionicons name="time" size={16} color="#f59e0b" />
              <Text style={styles.pendingText}>Pending</Text>
            </View>
          )}
          <Ionicons name="chevron-forward" size={20} color="#9ca3af" />
        </View>
      </View>
    </TouchableOpacity>
  );

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'active':
        return '#10b981';
      case 'pending':
        return '#f59e0b';
      case 'completed':
        return '#6b7280';
      default:
        return '#ef4444';
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#2563eb" />
        <Text style={styles.loadingText}>Loading permits...</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <View style={styles.brandContainer}>
            <Text style={styles.brandText}>GeoProx</Text>
          </View>
          <Text style={styles.subtitle}>
            Welcome back, {user?.username || 'User'}
          </Text>
        </View>
        <TouchableOpacity onPress={handleLogout} style={styles.logoutButton}>
          <Ionicons name="log-out-outline" size={24} color="#ef4444" />
        </TouchableOpacity>
      </View>

      <View style={styles.searchContainer}>
        <View style={styles.searchInputContainer}>
          <Ionicons name="search" size={20} color="#6b7280" style={styles.searchIcon} />
          <TextInput
            style={styles.searchInput}
            placeholder="Search permit references (e.g., HAW, K6004...)"
            placeholderTextColor="#9ca3af"
            value={searchQuery}
            onChangeText={handleSearch}
            autoCapitalize="none"
            autoCorrect={false}
          />
          {searchQuery.length > 0 && (
            <TouchableOpacity 
              onPress={() => handleSearch('')}
              style={styles.clearButton}
            >
              <Ionicons name="close-circle" size={20} color="#6b7280" />
            </TouchableOpacity>
          )}
        </View>
      </View>

      {permits.length === 0 ? (
        <View style={styles.emptyContainer}>
          <Ionicons name="document-text-outline" size={64} color="#9ca3af" />
          <Text style={styles.emptyTitle}>No Permits Found</Text>
          <Text style={styles.emptyText}>
            You don't have any permits assigned to you yet.
          </Text>
        </View>
      ) : (
        <FlatList
          data={filteredPermits}
          renderItem={renderPermitCard}
          keyExtractor={(item) => item.permit_ref}
          contentContainerStyle={styles.listContainer}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor="#2563eb"
            />
          }
          showsVerticalScrollIndicator={false}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f8fafc',
  },
  loadingText: {
    marginTop: 16,
    fontSize: 16,
    color: '#6b7280',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  subtitle: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  logoutButton: {
    padding: 8,
  },
  listContainer: {
    padding: 16,
  },
  permitCard: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  permitNumber: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    flex: 1,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statusText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
  cardContent: {
    marginBottom: 12,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  detailText: {
    marginLeft: 8,
    fontSize: 14,
    color: '#374151',
  },
  cardFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#e5e7eb',
  },
  addressText: {
    fontSize: 13,
    color: '#6b7280',
    flex: 1,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#374151',
    marginTop: 16,
    marginBottom: 8,
  },
  emptyText: {
    fontSize: 16,
    color: '#6b7280',
    textAlign: 'center',
    lineHeight: 24,
  },
  headerLeft: {
    flex: 1,
  },
  headerRight: {
    alignItems: 'flex-end',
  },
  permitName: {
    fontSize: 14,
    color: '#6b7280',
    marginTop: 2,
  },
  inspectionResults: {
    flexDirection: 'row',
    marginTop: 4,
  },
  resultBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    marginLeft: 4,
  },
  resultText: {
    color: '#ffffff',
    fontSize: 10,
    fontWeight: '600',
  },
  riskBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
  },
  riskText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
  coordinatesRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  coordinatesText: {
    marginLeft: 8,
    marginRight: 4,
    fontSize: 14,
    color: '#2563eb',
    textDecorationLine: 'underline',
  },
  footerRight: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  completedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 8,
  },
  completedText: {
    marginLeft: 4,
    fontSize: 12,
    color: '#10b981',
    fontWeight: '600',
  },
  pendingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 8,
  },
  pendingText: {
    marginLeft: 4,
    fontSize: 12,
    color: '#f59e0b',
    fontWeight: '600',
  },
  searchContainer: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  searchInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f9fafb',
    borderRadius: 8,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  searchIcon: {
    marginRight: 8,
  },
  searchInput: {
    flex: 1,
    paddingVertical: 10,
    fontSize: 16,
    color: '#1f2937',
  },
  clearButton: {
    padding: 4,
  },
  headerLeft: {
    flex: 1,
  },
  brandContainer: {
    marginBottom: 4,
  },
  brandText: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
    letterSpacing: 1,
  },
  statusContainer: {
    marginLeft: 8,
  },
  statusPending: {
    color: '#f59e0b',
    fontSize: 14,
    fontWeight: '600',
  },
  statusWip: {
    color: '#8b5cf6',
    fontSize: 14,
    fontWeight: '600',
  },
  statusCompleted: {
    color: '#10b981',
    fontSize: 14,
    fontWeight: '600',
  },
  resultsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 24,
  },
  resultLabel: {
    fontSize: 14,
    color: '#374151',
    fontWeight: '500',
  },
  sampleStatus: {
    fontSize: 14,
    color: '#6b7280',
    marginLeft: 8,
  },
  statusNotRequired: {
    color: '#6b7280',
    fontSize: 14,
    fontWeight: '600',
  },
  statusPendingSample: {
    color: '#f59e0b',
    fontSize: 14,
    fontWeight: '600',
  },
});
