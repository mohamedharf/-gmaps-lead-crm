from django import forms
from django.contrib.auth.models import User

from .models import SystemSettings, SalesAgentProfile

class SalesAgentForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True, label="الاسم الأول")
    last_name = forms.CharField(max_length=30, required=True, label="الاسم الأخير")
    username = forms.CharField(max_length=150, help_text="اسم المستخدم لتسجيل الدخول")
    password = forms.CharField(widget=forms.PasswordInput, help_text="كلمة المرور")
    email = forms.EmailField(required=False, label="البريد الإلكتروني")

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user

class SalesAgentProfileForm(forms.ModelForm):
    manager_user = forms.ModelChoiceField(
        queryset=User.objects.filter(groups__name='Sales'), 
        required=False,
        label='Assign Manager'
    )

    class Meta:
        model = SalesAgentProfile
        fields = ['commission_rate', 'team_commission_rate']
        widgets = {
            'commission_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'team_commission_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def save(self, commit=True):
        profile = super().save(commit=False)
        manager_user = self.cleaned_data.get('manager_user')
        if manager_user:
            manager_profile, _ = SalesAgentProfile.objects.get_or_create(user=manager_user)
            profile.manager = manager_profile
        else:
            profile.manager = None
            
        if commit:
            profile.save()
        return profile

class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ['site_name', 'logo', 'primary_color', 'secondary_color', 'text_color', 
                  'dark_primary_color', 'dark_secondary_color', 'dark_text_color',
                  'default_commission_rate', 'first_message_template', 'second_message_template']
        widgets = {
            'site_name': forms.TextInput(attrs={'class': 'form-control'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'primary_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'secondary_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'text_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'dark_primary_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'dark_secondary_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'dark_text_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'default_commission_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'first_message_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 10}),
            'second_message_template': forms.Textarea(attrs={'class': 'form-control', 'rows': 10}),
        }

class UserSettingsForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    profile_picture = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    phone_number = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+2010...'}))

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

class AdminAccountForm(forms.ModelForm):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    first_name = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'first_name', 'last_name']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        user.is_staff = True
        if commit:
            user.save()
        return user
