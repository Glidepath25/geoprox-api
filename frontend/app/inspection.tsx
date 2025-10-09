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
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';

const EXPO_PUBLIC_BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

interface Permit {
  id: string;
  permit_number: string;
  permit_name: string;
  works_type: string;
  location: string;
  address: string;
  latitude: number;
  longitude: number;
  highway_authority: string;
  proximity_risk_assessment: string;
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
  }, []);

  const requestPermissions = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Sorry, we need camera roll permissions to add photos.');
    }
  };

  const loadPermit = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      
      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/permits/${permitId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setPermit(data);
        setWorkOrderRef(data.permit_number.split('-')[0] || '');
        setExcavationSiteNumber('234');
      } else if (response.status === 401) {
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
    if (!workOrderRef.trim()) {
      Alert.alert('Validation Error', 'Work Order Reference is required');
      return false;
    }

    if (!excavationSiteNumber.trim()) {
      Alert.alert('Validation Error', 'Excavation Site Number is required');
      return false;
    }

    if (!utilityType.trim()) {
      Alert.alert('Validation Error', 'Utility Type is required');
      return false;
    }

    const unansweredQuestions = questions.filter(q => !q.answer);
    if (unansweredQuestions.length > 0) {
      Alert.alert('Validation Error', 'Please answer all questions');
      return false;
    }

    return true;
  };

  const saveInspection = async () => {
    setSaving(true);
    try {
      const token = await AsyncStorage.getItem('token');
      
      const inspectionData = {
        permit_id: permitId,
        work_order_reference: workOrderRef || '',
        excavation_site_number: excavationSiteNumber || '',
        surface_location: surfaceLocation,
        utility_type: utilityType || '',
        q1_asbestos: questions[0].answer,
        q1_notes: questions[0].notes,
        q2_binder_shiny: questions[1].answer,
        q2_notes: questions[1].notes,
        q3_spray_pak: questions[2].answer,
        q3_notes: questions[2].notes,
        q4_soil_stained: questions[3].answer,
        q4_notes: questions[3].notes,
        q5_water_moisture: questions[4].answer,
        q5_notes: questions[4].notes,
        q6_pungent_odours: questions[5].answer,
        q6_notes: questions[5].notes,
        q7_litmus_paper: questions[6].answer,
        q7_notes: questions[6].notes,
        bituminous_result: bituminousResult,
        sub_base_result: subBaseResult,
        photos: photos,
      };

      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/inspections/save`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(inspectionData),
      });

      if (response.ok) {
        Alert.alert('Saved', 'Inspection saved as draft. You can complete it later.');
      } else {
        const errorData = await response.json();
        Alert.alert('Error', errorData.detail || 'Failed to save inspection');
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
      const token = await AsyncStorage.getItem('token');
      
      const inspectionData = {
        permit_id: permitId,
        work_order_reference: workOrderRef,
        excavation_site_number: excavationSiteNumber,
        surface_location: surfaceLocation,
        utility_type: utilityType,
        q1_asbestos: questions[0].answer,
        q1_notes: questions[0].notes,
        q2_binder_shiny: questions[1].answer,
        q2_notes: questions[1].notes,
        q3_spray_pak: questions[2].answer,
        q3_notes: questions[2].notes,
        q4_soil_stained: questions[3].answer,
        q4_notes: questions[3].notes,
        q5_water_moisture: questions[4].answer,
        q5_notes: questions[4].notes,
        q6_pungent_odours: questions[5].answer,
        q6_notes: questions[5].notes,
        q7_litmus_paper: questions[6].answer,
        q7_notes: questions[6].notes,
        bituminous_result: bituminousResult,
        sub_base_result: subBaseResult,
        photos: photos,
      };

      const response = await fetch(`${EXPO_PUBLIC_BACKEND_URL}/api/inspections/submit`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(inspectionData),
      });

      if (response.ok) {
        Alert.alert(
          'Success',
          'Site inspection completed successfully!',
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
                <Text style={styles.detailLabel}>PERMIT NAME</Text>
                <Text style={styles.detailValue}>{permit?.permit_name}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>DATE OF ASSESSMENT</Text>
                <Text style={styles.detailValue}>{new Date().toISOString().split('T')[0]}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>LOCATION OF WORK</Text>
                <Text style={styles.detailValue}>{permit?.location}</Text>
              </View>
              
              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>PERMIT NUMBER</Text>
                <Text style={styles.detailValue}>{permit?.permit_number}</Text>
              </View>

              <View style={styles.detailItem}>
                <Text style={styles.detailLabel}>PROXIMITY RISK ASSESSMENT</Text>
                <Text style={styles.detailValue}>{permit?.proximity_risk_assessment}</Text>
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

          {/* Submit Button */}
          <View style={styles.submitSection}>
            <TouchableOpacity
              style={[styles.submitButton, submitting && styles.buttonDisabled]}
              onPress={submitInspection}
              disabled={submitting}
            >
              {submitting ? (
                <ActivityIndicator size="small" color="#ffffff" />
              ) : (
                <Text style={styles.submitButtonText}>Complete Site Assessment</Text>
              )}
            </TouchableOpacity>
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
  },
});