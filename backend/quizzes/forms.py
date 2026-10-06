from django import forms

from courses.models import Course
from .models import Quiz


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['titulo', 'descripcion', 'course']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, course_queryset=None, allow_course_change=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = course_queryset or Course.objects.none()
        self.fields['course'].disabled = not allow_course_change

