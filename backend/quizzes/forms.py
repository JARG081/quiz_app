from django import forms

from courses.models import Course
from .models import Quiz


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['titulo', 'descripcion', 'course', 'tiempo_por_pregunta']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, course_queryset=None, allow_course_change=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = course_queryset or Course.objects.none()
        self.fields['course'].disabled = not allow_course_change

    def clean_tiempo_por_pregunta(self):
        value = self.cleaned_data['tiempo_por_pregunta']
        if value < 5:
            raise forms.ValidationError('El tiempo mínimo por pregunta es 5 segundos.')
        if value > 120:
            raise forms.ValidationError('El tiempo máximo por pregunta es 120 segundos.')
        return value
