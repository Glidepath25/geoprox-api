import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Image,
  ActivityIndicator,
  Linking,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { TokenManager } from '../utils/tokenManager';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';

const EXPO_PUBLIC_BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

interface Permit {
  permit_ref: string;
  created_at: string;
  updated_at: string;
  location?: {
    display: string;
    lat: number;
    lon: number;
    radius_m: number;
  };
  desktop: {
    status: string;
    outcome: string | null;
  };
  site: {
    status: string;
    outcome: string | null;
  };
  sample: {
    status: string;
    outcome: string | null;
  };
  owner_username: string;
  owner_display_name: string;
}

interface Question {
  id: string;
  title: string;
  description: string;
  answer: 'Yes' | 'No' | '';
  notes: string;
}

export default function InspectionScreen() {
  const router = useRouter();
  const { permitId } = useLocalSearchParams();
  
  const [permit, setPermit] = useState<Permit | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [photos, setPhotos] = useState<string[]>([]);
  
  // Form fields
  const [workOrderRef, setWorkOrderRef] = useState('');
  const [excavationSiteNumber, setExcavationSiteNumber] = useState('');
  const [surfaceLocation, setSurfaceLocation] = useState('Footway / Footpath');
  const [utilityType, setUtilityType] = useState('');
  const [bituminousResult, setBituminousResult] = useState('Red');
  const [subBaseResult, setSubBaseResult] = useState('Green');
  
  // Questions state
  const [questions, setQuestions] = useState<Question[]>([
    {
      id: 'q1',
      title: 'Q1',
      description: 'Are there any signs of asbestos fibres or asbestos containing materials in the excavation?',
      answer: '',
      notes: 'If asbestos or signs of asbestos are identified the excavation does not qualify for a risk assessment.',
    },
    {
      id: 'q2', 
      title: 'Q2',
      description: 'Is the binder shiny, sticky to touch and is there an organic odour?',
      answer: '',
      notes: 'All three (shiny, sticky and creosote odour) required for a "yes".',
    },
    {
      id: 'q3',
      title: 'Q3',
      description: 'Spray PAK across the profile of asphalt / bitumen. Does the paint change colour to Band 1 or 2?',
      answer: '',
      notes: 'Ensure to spray a line across the full depth of the bituminous layer. Refer to PAK colour chart.',
    },
    {
      id: 'q4',
      title: 'Q4',
      description: 'Is the soil stained an unusual colour (such as orange, black, blue or green)?',
      answer: '',
      notes: 'Compare the discolouration of soil to other parts of the excavation.',
    },
    {
      id: 'q5',
      title: 'Q5',
      description: 'If there is water or moisture in the excavation, is there a rainbow sheen or colouration to the water?',
      answer: '',
      notes: 'Looking for signs of oil in the excavation.',
    },
    {
      id: 'q6',
      title: 'Q6',
      description: 'Are there any pungent odours to the material?',
      answer: '',
      notes: 'Think bleach, garlic, egg, tar, gas or other strong smells.',
    },
    {
      id: 'q7',
      title: 'Q7',
      description: 'Use litmus paper on wet soil, does it change colour to high or low pH?',
      answer: '',
      notes: 'Refer to the pH colour chart.',
    },
  ]);

  useEffect(() => {
    loadPermit();
    requestPermissions();
    loadExistingInspection();
  }, []);

  const requestPermissions = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Sorry, we need camera roll permissions to add photos.');
    }
  };

  const loadExistingInspection = async () => {
    try {
      const token = await TokenManager.getAccessToken();
      
      // Get permit details which includes site_payload for existing inspections
      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/permits/${permitId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const permitData = await response.json();
        
        // Check if there's existing inspection data in site_payload
        if (permitData.inspection_status === 'wip' || permitData.inspection_status === 'completed') {
          // The site_payload is stored in the backend, we'll load it from there
          // For now, we'll leave the form empty and let users re-enter
          console.log('Existing inspection status:', permitData.inspection_status);
        }
      }
    } catch (error) {
      console.log('No existing inspection found or error loading:', error);
      // This is fine - just means no existing inspection
    }
  };

  const loadPermit = async () => {
    try {
      const token = await TokenManager.getAccessToken();
      
      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/permits/${permitId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setPermit(data);
        setWorkOrderRef(data.permit_ref.split('-')[0] || '');
        setExcavationSiteNumber('234');
      } else if (response.status === 401) {
        await TokenManager.clearTokens();
        await AsyncStorage.clear();
        router.replace('/');
      } else {
        Alert.alert('Error', 'Failed to load permit details');
      }
    } catch (error) {
      console.error('Load permit error:', error);
      Alert.alert('Error', 'Network error loading permit');
    } finally {
      setLoading(false);
    }
  };

  const updateQuestion = (questionId: string, field: 'answer' | 'notes', value: string) => {
    setQuestions(prev => prev.map(q => 
      q.id === questionId ? { ...q, [field]: value } : q
    ));
  };

  const addPhoto = async () => {
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true,
        aspect: [4, 3],
        quality: 0.8,
        base64: true,
      });

      if (!result.canceled && result.assets[0].base64) {
        setPhotos(prev => [...prev, `data:image/jpeg;base64,${result.assets[0].base64}`]);
      }
    } catch (error) {
      console.error('Photo error:', error);
      Alert.alert('Error', 'Failed to add photo');
    }
  };

  const removePhoto = (index: number) => {
    Alert.alert(
      'Remove Photo',
      'Are you sure you want to remove this photo?',
      [
        { text: 'Cancel', style: 'cancel' },
        { 
          text: 'Remove', 
          style: 'destructive',
          onPress: () => setPhotos(prev => prev.filter((_, i) => i !== index))
        },
      ]
    );
  };

  const validateForm = () => {
    const missingFields = [];
    
    if (!workOrderRef.trim()) {
      missingFields.push('Work Order Reference');
    }

    if (!excavationSiteNumber.trim()) {
      missingFields.push('Excavation Site Number');
    }

    if (!utilityType.trim()) {
      missingFields.push('Utility Type');
    }

    const unansweredQuestions = questions.filter(q => !q.answer);
    if (unansweredQuestions.length > 0) {
      missingFields.push(`${unansweredQuestions.length} unanswered question(s)`);
    }

    if (missingFields.length > 0) {
      Alert.alert(
        'Submission Failed', 
        `Please complete the following mandatory fields:\n\n• ${missingFields.join('\n• ')}`,
        [{ text: 'OK', style: 'default' }]
      );
      return false;
    }

    return true;
  };

  const saveInspection = async () => {
    setSaving(true);
    try {
      const token = await TokenManager.getAccessToken();
      
      // Format data for production API
      const payload = {
        status: "In progress",
        notes: "Draft saved from mobile app",
        payload: {
          form: {
            permit_number: permitId,
            work_order_ref: workOrderRef || '',
            excavation_site_number: excavationSiteNumber || '',
            surface_location: surfaceLocation,
            utility_type: utilityType || '',
            q1_asbestos: questions[0].answer,
            q2_binder_shiny: questions[1].answer,
            q3_spray_pak: questions[2].answer,
            q4_soil_colour: questions[3].answer,
            q5_water_sheen: questions[4].answer,
            q6_pungent_odour: questions[5].answer,
            q7_litmus_change: questions[6].answer,
            result_bituminous: bituminousResult,
            result_sub_base: subBaseResult,
            assessment_date: new Date().toISOString().split('T')[0],
          },
          summary: {
            bituminous: "Pending",
            sub_base: "Pending"
          },
          attachments: photos
        }
      };

      console.log('Saving inspection with payload:', JSON.stringify(payload, null, 2));
      
      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/permits/${permitId}/site-assessment`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      console.log('Save response status:', response.status);
      const responseData = await response.json();
      console.log('Save response data:', responseData);

      if (response.ok) {
        Alert.alert('Saved', 'Inspection saved as draft. You can complete it later.');
        // Don't navigate back, let user continue working
      } else {
        Alert.alert('Error', responseData.detail || 'Failed to save inspection');
      }
    } catch (error) {
      console.error('Save error:', error);
      Alert.alert('Error', 'Network error saving inspection');
    } finally {
      setSaving(false);
    }
  };

  const submitInspection = async () => {
    if (!validateForm()) return;

    setSubmitting(true);
    try {
      const token = await TokenManager.getAccessToken();
      
      // Determine outcome based on results
      const outcome = (bituminousResult === 'Green' && subBaseResult === 'Green') ? 'Pass' : 'Fail';
      
      // Format data for production API
      const payload = {
        status: "Completed",
        outcome: outcome,
        notes: "Submitted from mobile app",
        payload: {
          form: {
            permit_number: permitId,
            work_order_ref: workOrderRef,
            excavation_site_number: excavationSiteNumber,
            surface_location: surfaceLocation,
            utility_type: utilityType,
            q1_asbestos: questions[0].answer,
            q2_binder_shiny: questions[1].answer,
            q3_spray_pak: questions[2].answer,
            q4_soil_colour: questions[3].answer,
            q5_water_sheen: questions[4].answer,
            q6_pungent_odour: questions[5].answer,
            q7_litmus_change: questions[6].answer,
            result_bituminous: bituminousResult,
            result_sub_base: subBaseResult,
            assessment_date: new Date().toISOString().split('T')[0],
            site_address: permit?.location?.display || '',
          },
          summary: {
            bituminous: bituminousResult,
            sub_base: subBaseResult
          },
          attachments: photos
        }
      };

      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/permits/${permitId}/site-assessment`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        Alert.alert(
          'Inspection Submitted',
          'Site inspection has been successfully submitted and marked as complete.',
          [{ text: 'OK', onPress: () => router.back() }]
        );
      } else {
        const errorData = await response.json();
        Alert.alert('Error', errorData.detail || 'Failed to submit inspection');
      }
    } catch (error) {
      console.error('Submit error:', error);
      Alert.alert('Error', 'Network error submitting inspection');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#2563eb" />
        <Text style={styles.loadingText}>Loading permit...</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
            <Ionicons name="arrow-back" size={24} color="#2563eb" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Site Assessment</Text>
          <View style={styles.placeholder} />
        </View>

        <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
          {/* Site Details */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Site details</Text>
            
            <View style={styles.detailsGrid}>
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>PERMIT REF</Text>
                <Text style={styles.detailValue}>{permit?.permit_ref}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>DATE OF ASSESSMENT</Text>
                <Text style={styles.detailValue}>{new Date().toISOString().split('T')[0]}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>LOCATION</Text>
                {permit?.location ? (
                  <TouchableOpacity
                    onPress={() => {
                      const url = `https://www.google.com/maps?q=${permit.location.lat},${permit.location.lon}`;
                      Linking.openURL(url);
                    }}
                    style={styles.locationLink}
                  >
                    <Text style={styles.locationText}>{permit.location.display}</Text>
                    <Ionicons name="open-outline" size={14} color="#2563eb" style={{ marginLeft: 4 }} />
                  </TouchableOpacity>
                ) : (
                  <Text style={styles.detailValue}>N/A</Text>
                )}
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>OWNER</Text>
                <Text style={styles.detailValue}>{permit?.owner_display_name}</Text>
              </View>

              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>DESKTOP OUTCOME</Text>
                <Text style={styles.detailValue}>{permit?.desktop?.outcome || 'N/A'}</Text>
              </View>
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>UTILITY TYPE *</Text>
              <TextInput
                style={styles.input}
                value={utilityType}
                onChangeText={setUtilityType}
                placeholder="Enter utility type observed on site (e.g., Gas, Electricity, Water)"
              />
            </View>

            <View style={styles.inputRow}>
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>WORK ORDER REFERENCE</Text>
                <TextInput
                  style={styles.input}
                  value={workOrderRef}
                  onChangeText={setWorkOrderRef}
                  placeholder="Enter work order reference"
                />
              </View>
              
              <View style={styles.inputContainer}>
                <Text style={styles.inputLabel}>EXCAVATION SITE NUMBER</Text>
                <TextInput
                  style={styles.input}
                  value={excavationSiteNumber}
                  onChangeText={setExcavationSiteNumber}
                  placeholder="Enter site number"
                />
              </View>
            </View>

            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>SURFACE LOCATION</Text>
              <TextInput
                style={styles.input}
                value={surfaceLocation}
                onChangeText={setSurfaceLocation}
                placeholder="Enter surface location"
              />
            </View>
          </View>

          {/* Questions */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Questionnaire responses</Text>
            
            {questions.map((question, index) => (
              <View key={question.id} style={styles.questionCard}>
                <View style={styles.questionHeader}>
                  <Text style={styles.questionRef}>{question.title}</Text>
                  <Text style={styles.questionText}>{question.description}</Text>
                </View>
                
                <View style={styles.answerSection}>
                  <View style={styles.radioGroup}>
                    <TouchableOpacity
                      style={[styles.radioOption, question.answer === 'Yes' && styles.radioSelected]}
                      onPress={() => updateQuestion(question.id, 'answer', 'Yes')}
                    >
                      <Text style={[styles.radioText, question.answer === 'Yes' && styles.radioTextSelected]}>
                        Yes
                      </Text>
                    </TouchableOpacity>
                    
                    <TouchableOpacity
                      style={[styles.radioOption, question.answer === 'No' && styles.radioSelected]}
                      onPress={() => updateQuestion(question.id, 'answer', 'No')}
                    >
                      <Text style={[styles.radioText, question.answer === 'No' && styles.radioTextSelected]}>
                        No
                      </Text>
                    </TouchableOpacity>
                  </View>
                  
                  <Text style={styles.notesLabel}>NOTES</Text>
                  <Text style={styles.notesText}>{question.notes}</Text>
                </View>
              </View>
            ))}
          </View>

          {/* Assessment Results */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Assessment results</Text>
            
            <View style={styles.resultsGrid}>
              <View style={styles.resultItem}>
                <Text style={styles.resultLabel}>BITUMINOUS</Text>
                <View style={styles.radioGroup}>
                  <TouchableOpacity
                    style={[styles.radioOption, bituminousResult === 'Red' && styles.radioSelected]}
                    onPress={() => setBituminousResult('Red')}
                  >
                    <Text style={[styles.radioText, bituminousResult === 'Red' && styles.radioTextSelected]}>
                      Red
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.radioOption, bituminousResult === 'Green' && styles.radioSelected]}
                    onPress={() => setBituminousResult('Green')}
                  >
                    <Text style={[styles.radioText, bituminousResult === 'Green' && styles.radioTextSelected]}>
                      Green
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>
              
              <View style={styles.resultItem}>
                <Text style={styles.resultLabel}>SUB-BASE</Text>
                <View style={styles.radioGroup}>
                  <TouchableOpacity
                    style={[styles.radioOption, subBaseResult === 'Red' && styles.radioSelected]}
                    onPress={() => setSubBaseResult('Red')}
                  >
                    <Text style={[styles.radioText, subBaseResult === 'Red' && styles.radioTextSelected]}>
                      Red
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.radioOption, subBaseResult === 'Green' && styles.radioSelected]}
                    onPress={() => setSubBaseResult('Green')}
                  >
                    <Text style={[styles.radioText, subBaseResult === 'Green' && styles.radioTextSelected]}>
                      Green
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
          </View>

          {/* Photos */}
          <View style={styles.section}>
            <View style={styles.photosHeader}>
              <Text style={styles.sectionTitle}>Photos</Text>
              <TouchableOpacity onPress={addPhoto} style={styles.addPhotoButton}>
                <Ionicons name="camera" size={20} color="#2563eb" />
                <Text style={styles.addPhotoText}>Add Photo</Text>
              </TouchableOpacity>
            </View>
            
            {photos.length === 0 ? (
              <View style={styles.noPhotos}>
                <Ionicons name="image-outline" size={48} color="#9ca3af" />
                <Text style={styles.noPhotosText}>No photos added yet</Text>
              </View>
            ) : (
              <View style={styles.photosGrid}>
                {photos.map((photo, index) => (
                  <View key={index} style={styles.photoContainer}>
                    <Image source={{ uri: photo }} style={styles.photo} />
                    <TouchableOpacity
                      onPress={() => removePhoto(index)}
                      style={styles.removePhotoButton}
                    >
                      <Ionicons name="close-circle" size={24} color="#ef4444" />
                    </TouchableOpacity>
                  </View>
                ))}
              </View>
            )}
          </View>

          {/* Submit Buttons */}
          <View style={styles.submitSection}>
            <View style={styles.buttonsContainer}>
              <TouchableOpacity
                style={[styles.saveButton, saving && styles.buttonDisabled]}
                onPress={saveInspection}
                disabled={saving || submitting}
              >
                {saving ? (
                  <ActivityIndicator size="small" color="#2563eb" />
                ) : (
                  <>
                    <Ionicons name="save-outline" size={20} color="#2563eb" />
                    <Text style={styles.saveButtonText}>Save Draft</Text>
                  </>
                )}
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.submitButton, submitting && styles.buttonDisabled]}
                onPress={submitInspection}
                disabled={submitting || saving}
              >
                {submitting ? (
                  <ActivityIndicator size="small" color="#ffffff" />
                ) : (
                  <>
                    <Ionicons name="checkmark-circle" size={20} color="#ffffff" />
                    <Text style={styles.submitButtonText}>Submit Final</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  keyboardView: {
    flex: 1,
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
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#ffffff',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
  },
  placeholder: {
    width: 40,
  },
  scrollView: {
    flex: 1,
  },
  section: {
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 12,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 16,
  },
  detailsGrid: {
    marginBottom: 16,
  },
  detailItem: {
    marginBottom: 12,
  },
  detailLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6b7280',
    marginBottom: 4,
    letterSpacing: 0.5,
  },
  detailValue: {
    fontSize: 16,
    color: '#1f2937',
  },
  locationLink: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
  },
  locationText: {
    fontSize: 16,
    color: '#2563eb',
    textDecorationLine: 'underline',
  },
  inputRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  inputContainer: {
    flex: 1,
    marginRight: 8,
  },
  inputLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6b7280',
    marginBottom: 6,
    letterSpacing: 0.5,
  },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
    backgroundColor: '#f9fafb',
    color: '#1f2937',
  },
  questionCard: {
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
    paddingVertical: 16,
  },
  questionHeader: {
    marginBottom: 16,
  },
  questionRef: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 4,
  },
  questionText: {
    fontSize: 15,
    color: '#374151',
    lineHeight: 22,
  },
  answerSection: {
    marginTop: 8,
  },
  radioGroup: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  radioOption: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 6,
    marginRight: 12,
    backgroundColor: '#ffffff',
  },
  radioSelected: {
    backgroundColor: '#2563eb',
    borderColor: '#2563eb',
  },
  radioText: {
    fontSize: 14,
    color: '#374151',
  },
  radioTextSelected: {
    color: '#ffffff',
  },
  notesLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: '#6b7280',
    marginBottom: 6,
    letterSpacing: 0.5,
  },
  notesText: {
    fontSize: 14,
    color: '#6b7280',
    lineHeight: 20,
  },
  resultsGrid: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  resultItem: {
    flex: 1,
    marginRight: 16,
  },
  resultLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1f2937',
    marginBottom: 12,
  },
  photosHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  addPhotoButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#eff6ff',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  addPhotoText: {
    marginLeft: 6,
    fontSize: 14,
    fontWeight: '600',
    color: '#2563eb',
  },
  noPhotos: {
    alignItems: 'center',
    padding: 32,
  },
  noPhotosText: {
    marginTop: 8,
    fontSize: 14,
    color: '#9ca3af',
  },
  photosGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  photoContainer: {
    position: 'relative',
    marginRight: 12,
    marginBottom: 12,
  },
  photo: {
    width: 80,
    height: 80,
    borderRadius: 8,
  },
  removePhotoButton: {
    position: 'absolute',
    top: -8,
    right: -8,
    backgroundColor: '#ffffff',
    borderRadius: 12,
  },
  submitSection: {
    padding: 16,
    marginBottom: 32,
  },
  submitButton: {
    backgroundColor: '#2563eb',
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  submitButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
  buttonsContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  saveButton: {
    flex: 1,
    backgroundColor: '#ffffff',
    borderWidth: 2,
    borderColor: '#2563eb',
    borderRadius: 12,
    paddingVertical: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveButtonText: {
    color: '#2563eb',
    fontSize: 16,
    fontWeight: '600',
    marginLeft: 8,
  },
});